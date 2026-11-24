"""第二批分钟因子（corr_vrlaglarge、core_up、core_down 及 pxret21 中性化）和旧仓 wx2 对拍。

数据来源：本地 PG（all_a 成员、日行情）与 lake 分钟分区，均只读；旧值来自
``tests/golden/market_data/minute_factors_2b/<YYYYMMDD>.json``。每个文件是一个截面日，``codes`` 是按代码排序
的股票范围，每个因子一个与 ``codes`` 等长的值数组（wx2 原样十进制字符串，无行为 null）。事件日 2026-03-02
的文件另含 ``pxret21`` 列，由 wx2 ``ASHAREEODPRICES.S_DQ_ADJCLOSE`` 按同一公式算出。

比对分三层：

1. 日值（逐截面日）：``corr_vrlaglarge``、``core_up``、``core_down`` 的每日值与 wx2 对拍。每只股票只有三类结果：

   - 一致：双方都有值且在 ``numeric(10,6)`` 存储精度内相等；或双方都无值。
   - 已裁定：旧有值，新无值，且该股票在当日是排除股票（负责人 2026-11-24 裁定，排除日当日无值）。
   - 其他：测试失败，不加例外。

2. 窗口均值（事件日 2026-03-02）：corr 取五日窗口，与 wx2 日值平均比较。窗口内有排除日的股票，
   先与原始均值比，再与扣除已裁定日后的均值比。core 的二十日均值没有单独输出，它的结果由第 3 层间接验证。

3. 中性化（事件日 2026-03-02）：用 wx2 窗口日值（扣除排除日）与 wx2 pxret21 走同一纯函数
   ``cross_section`` 算参考残差，与新残差比较。wx2 只存未中性化的值，参考残差因此是「旧公式 + 旧输入」，
   只能证明输入与公式一致，不能证明旧消费端的落库结果。输入是 6 位小数，残差容差 ``NEUTRAL_TOL`` 留给舍入。

pxret21 另做一项直接比对：本地日行情的 ``adj_close`` 算出的 pxret21 与 wx2 逐股票对拍。

截面日选择（见 ADR ``2026-11-24-minute-factors-batch-2b.md``）：2025-09-24 之后，避开 ``docs/adr`` 记录的分钟
修正日及其后 20 个开市日。事件日 2026-03-02 的 20 日窗口含 2026-01-26、01-27、01-29、01-30、02-03 的排除日。
"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from quantagent.adapters.lake.minute_bar import LakeMinuteBarRepository
from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.daily_prices import PostgresDailyPriceRepository
from quantagent.adapters.postgres.universe import PostgresUniverseRepository
from quantagent.contracts.loader import load_bundle
from quantagent.domain.calendar import open_dates
from quantagent.domain.universe.all_a import ALL_A_UNIVERSE_ID
from quantagent.features.library.cross_section import (
    mad_winsorize,
    residualize,
    utility_winsorize,
)
from quantagent.features.panel.minute_2b import (
    build_minute_2b_values,
    load_daily_2b,
    pxret21,
)
from quantagent.platform.config.settings import get_settings
from quantagent.platform.pg import connect
from quantagent.platform.storage.paths import detect_repo_root, resolve_var_paths

if TYPE_CHECKING:
    from collections.abc import Iterator

    from quantagent.domain.prices.types import DailyPrice
    from quantagent.features.panel.minute_2b import MinuteDay2b

FIXTURE_DIR = Path(__file__).parents[1] / "golden" / "market_data" / "minute_factors_2b"
AS_OF = date(2026, 11, 23)
EVENT = date(2026, 3, 2)
DAILY_DAYS = (date(2025, 9, 24), date(2025, 10, 15), EVENT)
MINUTE_DATASET = "src.minprice.ashare_minute_bar"
PRICE_DATASET = "src.wind.ashareeodprices"
CORR_ID = "pf_single_corr_vrlaglarge_5_mean_neg"
UP_ID = "pf_single_core_up_20_mean_pos_neut_pxret21"
DOWN_ID = "pf_single_core_down_20_mean_neg_neut_pxret21"
# wx2 列名 -> 因子 id 与窗口长度。core 的二十日均值只参与中性化，不单独输出。
FACTORS = {
    "corr_vrlaglarge": {"feature": CORR_ID, "window": 5},
    "core_up": {"feature": UP_ID, "window": 20},
    "core_down": {"feature": DOWN_ID, "window": 20},
}
# numeric(10,6) 的半个最小单位，加上浮点余量。
TOL = Decimal("0.0000005") + Decimal("0.000000001")
# 残差容差：wx2 日值是 6 位小数，20 日均值与截面回归会放大舍入误差。实测最大差约 2.5e-7，留出余量。
NEUTRAL_TOL = 1e-5
PXRET_TOL = 1e-9


@dataclass(frozen=True)
class _Event:
    """事件日比对的共享数据：窗口日、旧值、本地日值、排除集、股票池与事件日的 pxret 列。"""

    window: tuple[date, ...]
    fixtures: dict[date, _Fixture]
    local: dict[date, dict[str, MinuteDay2b]]
    excluded: dict[date, frozenset[str]]
    scope: frozenset[str]
    event: _Fixture


@dataclass(frozen=True)
class _Fixture:
    day: date
    codes: tuple[str, ...]
    columns: dict[str, dict[str, Decimal | None]]
    pxret: dict[str, Decimal | None] | None


def _ymd(day: date) -> str:
    return day.strftime("%Y%m%d")


def _load_fixture(day: date) -> _Fixture:
    doc = json.loads((FIXTURE_DIR / f"{_ymd(day)}.json").read_text(encoding="utf-8"))
    codes: list[str] = doc["codes"]
    if codes != sorted(set(codes)):
        raise ValueError(f"fixture {day} 的 codes 不是升序去重")
    columns: dict[str, dict[str, Decimal | None]] = {}
    for name in FACTORS:
        column = doc["columns"][name]
        if len(column) != len(codes):
            raise ValueError(f"fixture {day} 的 {name} 与 codes 长度不等")
        columns[name] = {
            code: None if value is None else Decimal(value)
            for code, value in zip(codes, column, strict=True)
        }
    pxret = None
    if "pxret21" in doc["columns"]:
        pxret = {
            code: None if value is None else Decimal(value)
            for code, value in zip(codes, doc["columns"]["pxret21"], strict=True)
        }
    return _Fixture(day=day, codes=tuple(codes), columns=columns, pxret=pxret)


def _classify(old: Decimal | None, new: float | None, *, excluded: bool) -> tuple[str, str]:
    """单只股票单日的分类。返回 (一致 / 已裁定 / 其他, 原因)。"""
    if old is None and new is None:
        return "一致", "双方无值"
    if old is not None and new is not None:
        if abs(Decimal(repr(new)) - old) > TOL:
            return "其他", f"数值不同 old={old} new={new!r}"
        return "一致", "精确或舍入边界内"
    if old is None:
        return "其他", f"新有值、旧无值 new={new!r}"
    if excluded:
        return "已裁定", "排除日当日无值"
    return "其他", f"旧有值 {old}，新无值，且不是排除日"


class _Context:
    """缓存每日的日值与排除集，只读访问本地 PG 与 lake。"""

    def __init__(self) -> None:
        settings = get_settings()
        paths = resolve_var_paths(settings, repo_root=detect_repo_root())
        self.conn = connect(settings, "src")
        self.conn.read_only = True
        calendar = LakeCalendarRepository(paths.lake / "std" / "trade_calendar")
        self.repo = LakeMinuteBarRepository(
            self.conn, paths.lake / "src" / "minprice" / "ashare_minute_bar", calendar
        )
        self.universe = PostgresUniverseRepository(self.conn)
        self.prices = PostgresDailyPriceRepository(self.conn)
        self.opens: tuple[date, ...] = tuple(
            open_dates(
                calendar.list_days(as_of=AS_OF, exchange="SSE", start=date(2025, 6, 1), end=AS_OF)
            )
        )
        self.bundle = load_bundle()
        self._daily: dict[tuple[date, frozenset[str]], dict[str, MinuteDay2b]] = {}

    def close(self) -> None:
        self.conn.close()

    def all_a(self, day: date) -> frozenset[str]:
        members = self.universe.members_at(as_of=AS_OF, dt=day, universe_id=ALL_A_UNIVERSE_ID)
        return frozenset(member.asset_id for member in members)

    def excluded(self, day: date) -> frozenset[str]:
        return self.repo.excluded_codes(as_of=AS_OF, day=day)

    def daily(self, day: date, scope: frozenset[str]) -> dict[str, MinuteDay2b]:
        key = (day, scope)
        if key not in self._daily:
            self._daily[key] = load_daily_2b(self.repo, as_of=AS_OF, day=day, codes=scope)
        return self._daily[key]


@pytest.fixture(scope="module")
def ctx() -> Iterator[_Context]:
    context = _Context()
    yield context
    context.close()


@pytest.mark.integration
@pytest.mark.parametrize("day", DAILY_DAYS, ids=lambda d: d.isoformat())
def test_daily_values_match_wx2_with_adjudicated_differences_only(ctx: _Context, day: date) -> None:
    started = time.perf_counter()
    fixture = _load_fixture(day)
    scope = ctx.all_a(day)
    assert scope <= set(fixture.codes), f"{day} 的 all_a 不在 fixture 范围内"
    excluded = ctx.excluded(day)
    daily = ctx.daily(day, scope)
    others: dict[str, list[str]] = {}
    for name, spec in FACTORS.items():
        counts: Counter[str] = Counter()
        factor_others: list[str] = []
        for code in sorted(scope):
            old = fixture.columns[name][code]
            row = daily.get(code)
            new = None if row is None else getattr(row, name)
            category, reason = _classify(old, new, excluded=code in excluded)
            counts[category] += 1
            if category == "其他":
                factor_others.append(f"{code} {reason}")
        print(
            f"[daily] {day.isoformat()} {spec['feature']}: all_a={len(scope)} "
            f"一致={counts['一致']} 已裁定={counts['已裁定']} 其他={counts['其他']}"
        )
        if factor_others:
            others[name] = factor_others
    print(f"[daily] {day.isoformat()} elapsed={time.perf_counter() - started:.1f}s")
    assert not others, {name: items[:20] for name, items in others.items()}


@pytest.mark.integration
def test_event_day_pxret_window_means_and_residuals_match_wx2(ctx: _Context) -> None:
    started = time.perf_counter()
    idx = ctx.opens.index(EVENT)
    window = ctx.opens[idx - 19 : idx + 1]
    base = ctx.opens[idx - 20]
    scope = ctx.all_a(EVENT)
    fixtures = {day: _load_fixture(day) for day in window}
    event_fixture = fixtures[EVENT]
    assert event_fixture.pxret is not None
    assert scope <= set(event_fixture.codes)
    data = _Event(
        window=window,
        fixtures=fixtures,
        local={day: ctx.daily(day, scope) for day in window},
        excluded={day: ctx.excluded(day) for day in window},
        scope=scope,
        event=event_fixture,
    )

    _check_pxret(ctx, scope, base, event_fixture)
    produced = _produce_event(ctx, scope)
    _report_exclusion_hits(data)
    _check_corr_means(data, produced)
    _check_neutral(data, produced)
    print(f"[event] elapsed={time.perf_counter() - started:.1f}s")


def _check_pxret(ctx: _Context, scope: frozenset[str], base: date, fixture: _Fixture) -> None:
    assert fixture.pxret is not None
    prices: tuple[DailyPrice, ...] = ctx.prices.list_prices(
        as_of=AS_OF, start=base, end=EVENT, wind_codes=tuple(sorted(scope))
    )
    px = {
        (row.wind_code, row.trade_dt): float(row.adj_close)
        for row in prices
        if row.adj_close is not None
    }
    mismatch: list[str] = []
    checked = 0
    for code in sorted(scope):
        want = fixture.pxret[code]
        got = pxret21(px.get((code, base)), px.get((code, EVENT)))
        if want is None and got is None:
            continue
        checked += 1
        if want is None or got is None or abs(Decimal(repr(got)) - want) > Decimal(str(PXRET_TOL)):
            mismatch.append(f"{code} wx2={want} local={got}")
    print(f"[pxret] checked={checked} mismatch={len(mismatch)}")
    assert not mismatch, mismatch[:20]


def _produce_event(ctx: _Context, scope: frozenset[str]) -> dict[tuple[str, str], Decimal]:
    """生产路径在事件日的输出，按 (feature_id, code) 索引。"""
    rows = build_minute_2b_values(
        ctx.repo,
        ctx.prices,
        as_of=AS_OF,
        opens=ctx.opens,
        start=EVENT,
        end=EVENT,
        minute_contract=ctx.bundle.visibilities[MINUTE_DATASET],
        price_contract=ctx.bundle.visibilities[PRICE_DATASET],
        universe_at=lambda _day: tuple(sorted(scope)),
        computed_at=datetime(2026, 11, 24),
        run_id="golden-minute-factors-2b",
        feature_ids=(CORR_ID, UP_ID, DOWN_ID),
    )
    assert {row.knowledge_dt for row in rows} == {EVENT}
    assert {row.pit_grade for row in rows} == {"A"}
    return {(row.feature_id, row.asset_id): Decimal(repr(row.value)) for row in rows}


def _report_exclusion_hits(data: _Event) -> None:
    """窗口内被排除且 wx2 有值的（股票, 日）数。这些是 20 日均值与残差里需要扣除的样本。"""
    for name, spec in FACTORS.items():
        hits = 0
        for day in data.window:
            for code in data.scope & data.excluded[day]:
                if data.fixtures[day].columns[name][code] is not None:
                    hits += 1
        print(
            f"[exclusion] {spec['feature']} window={data.window[0]}..{data.window[-1]} "
            f"wx2有值的排除样本={hits}"
        )


def _check_corr_means(data: _Event, produced: dict[tuple[str, str], Decimal]) -> None:
    window5 = data.window[-5:]
    counts: Counter[str] = Counter()
    others: list[str] = []
    for code in sorted(data.scope):
        category, detail = _mean_row(
            "corr_vrlaglarge",
            code,
            window5,
            data,
            sign=Decimal("-1"),
            got=produced.get((CORR_ID, code)),
        )
        counts[category] += 1
        if category == "其他":
            others.append(f"{code} {detail}")
    print(
        f"[mean] {EVENT.isoformat()} corr 五日 all_a={len(data.scope)} 一致={counts['一致']} "
        f"已裁定={counts['已裁定']} 其他={counts['其他']}"
    )
    assert not others, others[:20]


def _check_neutral(data: _Event, produced: dict[tuple[str, str], Decimal]) -> None:
    pxret = data.event.pxret
    assert pxret is not None
    x_ref = {code: float(value) for code, value in pxret.items() if value is not None}
    counts: Counter[str] = Counter()
    others: list[str] = []
    max_diff = 0.0
    for name, feature_id, sign in (
        ("core_up", UP_ID, Decimal("1")),
        ("core_down", DOWN_ID, Decimal("-1")),
    ):
        y_ref: dict[str, float] = {}
        for code in sorted(data.scope):
            values = _recon_values(name, code, data)
            if values:
                y_ref[code] = float(sign * sum(values) / len(values))
        reference = residualize(mad_winsorize(y_ref), utility_winsorize(x_ref), min_obs=20)
        emitted = {code for fid, code in produced if fid == feature_id}
        for code in sorted(data.scope | emitted):
            ours = produced.get((feature_id, code))
            ref = reference.get(code)
            if ours is None and ref is None:
                counts["一致"] += 1
                continue
            if ours is None or ref is None:
                counts["其他"] += 1
                others.append(f"{feature_id} {code} ours={ours} ref={ref}")
                continue
            diff = abs(float(ours) - ref)
            max_diff = max(max_diff, diff)
            if diff <= NEUTRAL_TOL:
                counts["一致"] += 1
            else:
                counts["其他"] += 1
                others.append(f"{feature_id} {code} ours={ours} ref={ref} diff={diff}")
    print(
        f"[neutral] {EVENT.isoformat()} 一致={counts['一致']} 其他={counts['其他']} "
        f"最大残差差={max_diff:.3e} 容差={NEUTRAL_TOL}"
    )
    assert not others, others[:20]


def _recon_values(name: str, code: str, data: _Event) -> list[Decimal]:
    """窗口内 wx2 有值且本地同日一致（或扣除排除日）的日值，即参考均值的样本。"""
    out: list[Decimal] = []
    for day in data.window:
        old = data.fixtures[day].columns[name][code]
        row = data.local[day].get(code)
        new = None if row is None else getattr(row, name)
        category, _ = _classify(old, new, excluded=code in data.excluded[day])
        if category == "一致" and old is not None:
            out.append(old)
    return out


def _mean_row(
    name: str,
    code: str,
    window: tuple[date, ...],
    data: _Event,
    *,
    sign: Decimal,
    got: Decimal | None,
) -> tuple[str, str]:
    """一只股票的窗口均值比对。先与原始均值比，再与扣除已裁定日后的均值比。"""
    raw: list[Decimal] = []
    blocked: list[str] = []
    for day in window:
        old = data.fixtures[day].columns[name][code]
        row = data.local[day].get(code)
        new = None if row is None else getattr(row, name)
        category, reason = _classify(old, new, excluded=code in data.excluded[day])
        if old is not None:
            raw.append(old)
        if category == "其他":
            blocked.append(f"{day.isoformat()} {reason}")
    if blocked:
        return "其他", f"窗口内单日其他差异 {blocked[:3]}"
    recon = _recon_values(name, code, data)
    raw_mean = sign * sum(raw) / len(raw) if raw else None
    recon_mean = sign * sum(recon) / len(recon) if recon else None
    if got is None and raw_mean is None:
        return "一致", "双方无值"
    if got is not None and raw_mean is not None and abs(got - raw_mean) <= TOL:
        return "一致", "原始均值"
    if got is None and recon_mean is None:
        return "已裁定", "窗口内无可用日值"
    if got is not None and recon_mean is not None and abs(got - recon_mean) <= TOL:
        return "已裁定", "扣除排除日后的均值"
    return "其他", f"got={got} raw={raw_mean} recon={recon_mean}"
