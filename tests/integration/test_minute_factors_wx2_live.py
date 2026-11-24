"""分钟因子日值与 5 日均值，和旧仓 wx2 ``stock_<factor>`` 对拍。

数据来源：本地 PG（all_a 成员）与 lake 分钟分区，均只读；旧值来自
``tests/golden/market_data/minute_factors/<YYYYMMDD>.json``，每个文件是一个截面日。
``codes`` 是按代码排序的股票范围，每个因子一个与 ``codes`` 等长的值数组（wx2 原样十进制字符串，
无行为则为 null），provenance 记录 SQL、范围与抓取日期。

每个 (因子, 股票, 日) 的比对只有三类结果：

- 一致：双方都有值且在旧表存储精度内相等；或双方都无值。
- 已裁定：新值为缺失，旧值为假 0，且条件在分钟数据中逐行核实成立。三种：
  排除日当日无值（负责人 2026-11-24 裁定 1）；ratio 的上行或下行不超过 1 根（裁定 2）；
  real_kurt 经 pandas nankurt 判为零方差（裁定 3）。判定式与 pandas 源码行号见
  ``is_pandas_zero_variance``；本测试另用 ``pandas.Series.kurt`` 复核同一结论。
- 其他：不属于上面任何一类。测试失败，不加例外。

5 日均值层面只在排除日窗口 2026-01-30 上比对。窗口日的旧值与新值都按事件日股票池取，
与生产读取窗口的范围一致。其余截面日只比对当日日值。

未纳入 golden 的日期：2024-08 至 2025-08 的旧表不可复现。抽样显示旧表与新数据的一致率约 7%，
2025-09-24 起全部一致。未判定哪一边对（旧表的计算问题或新数据的问题），因此 golden 只用
2025-09-24 之后的日期。
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

import pandas as pd
import pytest

from quantagent.adapters.lake.minute_bar import LakeMinuteBarRepository
from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.universe import PostgresUniverseRepository
from quantagent.contracts.loader import load_bundle
from quantagent.domain.calendar import open_dates
from quantagent.domain.universe.all_a import ALL_A_UNIVERSE_ID
from quantagent.features.library.minute.five_day import SIGN, SPECS
from quantagent.features.library.minute.intraday import is_pandas_zero_variance
from quantagent.features.panel.minute import (
    MINUTE_COLUMNS,
    build_minute_factor_values,
    load_daily_stats,
)
from quantagent.platform.config.settings import get_settings
from quantagent.platform.pg import connect
from quantagent.platform.storage.paths import detect_repo_root, resolve_var_paths

if TYPE_CHECKING:
    from collections.abc import Iterator

    from quantagent.features.library.minute.intraday import MinuteDayStats

FIXTURE_DIR = Path(__file__).parents[1] / "golden" / "market_data" / "minute_factors"
AS_OF = date(2026, 11, 23)
DATASET = "src.minprice.ashare_minute_bar"
FACTORS = ("corr_vrlag", "real_kurt", "ratio_realupvar", "ratio_realdownvar")
# 四个截面日（2025-09-24 之后、跨不同月份，四个因子在旧表与新数据上可对拍）
# + 排除日窗口 2026-01-26..01-30 的五个开市日。2024-08 至 2025-08 的旧表不可复现，见模块说明。
GOLDEN_DAYS = (
    date(2025, 9, 24),
    date(2025, 12, 22),
    date(2026, 2, 26),
    date(2026, 6, 1),
    date(2026, 1, 26),
    date(2026, 1, 27),
    date(2026, 1, 28),
    date(2026, 1, 29),
    date(2026, 1, 30),
)
EXCLUSION_EVENT = date(2026, 1, 30)
# numeric(10,6) 的半个最小单位，加上浮点余量。
TOL = Decimal("0.0000005") + Decimal("0.000000001")
_SIGN = Decimal(repr(SIGN))


@dataclass(frozen=True)
class _Evidence:
    """一只股票一天的收益形态，用于核实假 0 的条件。"""

    up: int
    down: int
    # 收益全部相同，仅用于 ratio 的假 0 判据（与旧判据一致）。
    constant: bool
    # pandas nankurt 判零方差，见 ``is_pandas_zero_variance``，用于 real_kurt 的假 0 判据。
    pandas_zero: bool


@dataclass
class _Day:
    scope: frozenset[str]
    excluded: frozenset[str]
    stats: dict[str, MinuteDayStats]
    evidence: dict[str, _Evidence]
    old: dict[str, dict[str, Decimal]]
    provenance: dict[str, object]


def _ymd(day: date) -> str:
    return day.strftime("%Y%m%d")


def _load_fixture(
    day: date,
) -> tuple[dict[str, dict[str, Decimal]], dict[str, object], frozenset[str]]:
    """读取截面日 ``day`` 的 fixture，返回 (因子 -> 代码 -> 旧值，provenance，覆盖的代码集合)。

    null 表示 wx2 对该股票没有行，与旧代码的 ``.get(code) is None`` 语义相同。
    """
    doc = json.loads((FIXTURE_DIR / f"{_ymd(day)}.json").read_text(encoding="utf-8"))
    codes: list[str] = doc["codes"]
    provenance: dict[str, object] = doc["provenance"]
    if codes != sorted(set(codes)) or len(codes) != provenance["scope_count"]:
        raise ValueError(f"fixture {day} 的 codes 不是升序去重或与 scope_count 不符")
    old: dict[str, dict[str, Decimal]] = {}
    for factor in FACTORS:
        column = doc["columns"][factor]
        if len(column) != len(codes):
            raise ValueError(f"fixture {day} 的 {factor} 与 codes 长度不等")
        old[factor] = {
            code: Decimal(value)
            for code, value in zip(codes, column, strict=True)
            if value is not None
        }
    return old, provenance, frozenset(codes)


def _evidence(rows: list[dict[str, object]]) -> dict[str, _Evidence]:
    """与 ``load_daily_stats`` 读到的同一份分钟行，算上行、下行根数与 pandas 零方差判定。

    同时用 ``pandas.Series.kurt`` 复核：两者结论不一致即停止，不以任一方为准。
    """
    by_code: dict[str, list[tuple[datetime, float]]] = {}
    for row in rows:
        by_code.setdefault(str(row["ts_code"]), []).append(
            (row["trade_time"], float(row["close"]))  # type: ignore[arg-type]
        )
    out: dict[str, _Evidence] = {}
    for code, items in by_code.items():
        items.sort(key=lambda item: item[0])
        closes = [close for _, close in items]
        rets = [closes[i + 1] / closes[i] - 1.0 for i in range(len(closes) - 1)]
        ours = is_pandas_zero_variance(rets)
        pandas_says_zero = bool(pd.Series(rets, dtype="float64").kurt() == 0.0)
        if ours != pandas_says_zero:
            raise AssertionError(f"{code} 零方差判定与 pandas 不一致: ours={ours}")
        out[code] = _Evidence(
            up=sum(1 for r in rets if r > 0),
            down=sum(1 for r in rets if r < 0),
            constant=all(r == rets[0] for r in rets),
            pandas_zero=ours,
        )
    return out


class _Context:
    """缓存每日的股票范围、排除集、新日值、收益形态与旧值。只读访问本地 PG 与 lake。"""

    def __init__(self) -> None:
        settings = get_settings()
        paths = resolve_var_paths(settings, repo_root=detect_repo_root())
        self.conn = connect(settings, "src")
        self.conn.read_only = True
        self.calendar = LakeCalendarRepository(paths.lake / "std" / "trade_calendar")
        self.repo = LakeMinuteBarRepository(
            self.conn, paths.lake / "src" / "minprice" / "ashare_minute_bar", self.calendar
        )
        self.universe = PostgresUniverseRepository(self.conn)
        days = self.calendar.list_days(
            as_of=AS_OF, exchange="SSE", start=date(2024, 6, 1), end=AS_OF
        )
        self.opens: tuple[date, ...] = tuple(open_dates(days))
        self._days: dict[tuple[date, frozenset[str]], _Day] = {}

    def close(self) -> None:
        self.conn.close()

    def all_a(self, day: date) -> frozenset[str]:
        members = self.universe.members_at(as_of=AS_OF, dt=day, universe_id=ALL_A_UNIVERSE_ID)
        return frozenset(member.asset_id for member in members)

    def day(self, day: date, scope: frozenset[str] | None = None) -> _Day:
        """``scope`` 默认是 ``day`` 当日的 all_a。窗口日取事件日股票池时显式传入。"""
        members = self.all_a(day) if scope is None else scope
        key = (day, members)
        if key not in self._days:
            excluded = self.repo.excluded_codes(as_of=AS_OF, day=day)
            stats = load_daily_stats(self.repo, as_of=AS_OF, day=day, codes=members)
            requested = sorted(members - excluded)
            evidence: dict[str, _Evidence] = {}
            if requested:
                table = self.repo.scan_window(
                    as_of=AS_OF,
                    start=day,
                    end=day,
                    codes=requested,
                    columns=MINUTE_COLUMNS,
                )
                evidence = _evidence(table.to_pylist())
            old, provenance, fixture_codes = _load_fixture(day)
            # 比对范围必须被 fixture 覆盖；否则缺失的股票会被静默当作 wx2 无行。
            uncovered = members - fixture_codes
            if uncovered:
                raise AssertionError(f"{day} 的比对范围有 {len(uncovered)} 只不在 fixture 中")
            self._days[key] = _Day(members, excluded, stats, evidence, old, provenance)
        return self._days[key]


@pytest.fixture(scope="module")
def ctx() -> Iterator[_Context]:
    context = _Context()
    yield context
    context.close()


def _missing_reason(factor: str, code: str, day: _Day, old: Decimal) -> str | None:
    """旧有值、新无值时，返回满足的已裁定条件；都不满足则为 None。"""
    if code in day.excluded:
        return "排除日当日无值"
    ev = day.evidence.get(code)
    if old != 0 or ev is None:
        return None
    if factor == "real_kurt" and ev.pandas_zero:
        return "real_kurt pandas 零方差"
    if factor == "ratio_realupvar" and ev.up <= 1 and not ev.constant:
        return "ratio_realupvar 上行不超过 1 根（假 0）"
    if factor == "ratio_realdownvar" and ev.down <= 1 and not ev.constant:
        return "ratio_realdownvar 下行不超过 1 根（假 0）"
    return None


def _classify_daily(
    factor: str, code: str, day: _Day, old: Decimal | None, new: float | None
) -> tuple[str, str]:
    """返回 (类别, 原因)。类别为 一致 / 已裁定 / 其他。"""
    if old is None and new is None:
        return "一致", "双方无值"
    if old is not None and new is not None:
        if abs(Decimal(repr(new)) - old) > TOL:
            return "其他", f"数值不同 old={old} new={new!r}"
        exact = round(Decimal(repr(new)), 6) == old
        return "一致", "精确" if exact else "舍入边界内"
    if old is None:
        return "其他", f"新有值、旧无值 new={new!r}"
    reason = _missing_reason(factor, code, day, old)
    if reason is None:
        return "其他", f"旧有值 {old}，新无值，已裁定条件不成立"
    return "已裁定", reason


@pytest.mark.integration
@pytest.mark.parametrize("day", GOLDEN_DAYS, ids=lambda d: d.isoformat())
def test_daily_values_match_wx2_with_adjudicated_differences_only(ctx: _Context, day: date) -> None:
    started = time.perf_counter()
    data = ctx.day(day)
    others: dict[str, list[str]] = {}
    # fixture 的股票范围必须仍是当前 all_a 成员，否则比对范围已变。
    assert data.provenance["all_a_count"] == len(data.scope), day
    for factor in FACTORS:
        counts: Counter[str] = Counter()
        factor_others: list[str] = []
        local = 0
        for code in sorted(data.scope):
            old = data.old[factor].get(code)
            stat = data.stats.get(code)
            new = getattr(stat, factor) if stat is not None else None
            if new is not None:
                local += 1
            category, reason = _classify_daily(factor, code, data, old, new)
            counts[category] += 1
            if category == "已裁定":
                counts[reason] += 1
            if category == "其他":
                factor_others.append(f"{code} {reason}")
        adjudicated = {key: n for key, n in counts.items() if key not in {"一致", "已裁定", "其他"}}
        print(
            f"[daily] {day.isoformat()} {factor}: all_a={len(data.scope)} "
            f"wx2_in_scope={len(data.old[factor])} local_values={local} "
            f"一致={counts['一致']} 已裁定={counts['已裁定']} 其他={counts['其他']} "
            f"已裁定明细={adjudicated}"
        )
        if factor_others:
            others[factor] = factor_others
    print(f"[daily] {day.isoformat()} elapsed={time.perf_counter() - started:.1f}s")
    assert not others, {factor: items[:20] for factor, items in others.items()}


def _mean_row(
    factor: str,
    code: str,
    got: Decimal | None,
    window: tuple[date, ...],
    window_data: dict[date, _Day],
) -> tuple[str, str]:
    """比对一只股票的五日均值。返回 (类别, 说明)。类别为 一致 / 已裁定 / 其他。

    先逐日分类：窗口内任一日为其他差异则整行为其他。否则按一致的日值算原始均值，
    按扣除已裁定日后的日值算重算均值。新值与原始均值一致为一致；与重算均值一致为已裁定。
    """
    raw: list[Decimal | None] = []
    recon: list[Decimal | None] = []
    reasons: list[str] = []
    blocked: list[str] = []
    for day in window:
        data = window_data[day]
        old = data.old[factor].get(code)
        stat = data.stats.get(code)
        new = getattr(stat, factor) if stat is not None else None
        category, reason = _classify_daily(factor, code, data, old, new)
        raw.append(old)
        if category == "一致":
            recon.append(old)
        else:
            recon.append(None)
            if category == "已裁定":
                reasons.append(f"{day.isoformat()} {reason}")
            else:
                blocked.append(f"{day.isoformat()} {reason}")
    if blocked:
        return "其他", f"窗口内单日其他差异 {blocked}"
    raw_valid = [v for v in raw if v is not None]
    recon_valid = [v for v in recon if v is not None]
    expected_raw = _SIGN * sum(raw_valid) / len(raw_valid) if raw_valid else None
    expected_recon = _SIGN * sum(recon_valid) / len(recon_valid) if recon_valid else None
    if got is None and expected_raw is None:
        return "一致", "双方无值"
    if got is not None and expected_raw is not None and abs(got - expected_raw) <= TOL:
        return "一致", "原始均值"
    kinds = "；".join(sorted({reason.split(" ", 1)[1] for reason in reasons}))
    if got is None and expected_recon is None:
        return "已裁定", f"窗口内无可用日值：{kinds}"
    if got is not None and expected_recon is not None and abs(got - expected_recon) <= TOL:
        return "已裁定", kinds
    return "其他", f"got={got} raw={expected_raw} recon={expected_recon} reasons={reasons}"


@pytest.mark.integration
def test_five_day_mean_matches_wx2_on_exclusion_window(ctx: _Context) -> None:
    started = time.perf_counter()
    idx = ctx.opens.index(EXCLUSION_EVENT)
    window = ctx.opens[idx - 4 : idx + 1]
    assert list(window) == list(GOLDEN_DAYS[-5:])
    event_scope = ctx.day(EXCLUSION_EVENT).scope
    universe = sorted(event_scope)
    # 生产读取窗口日时用事件日股票池，因此窗口日数据也按事件日股票池取。
    window_data = {day: ctx.day(day, event_scope) for day in window}
    rows = build_minute_factor_values(
        ctx.repo,
        as_of=AS_OF,
        opens=ctx.opens,
        start=EXCLUSION_EVENT,
        end=EXCLUSION_EVENT,
        contract=load_bundle().visibilities[DATASET],
        universe_at=lambda _day: universe,
        computed_at=datetime(2026, 11, 24),
        run_id="golden-minute-factors",
    )
    produced = {(row.feature_id, row.asset_id): Decimal(repr(row.value)) for row in rows}
    counts: Counter[str] = Counter()
    others: list[str] = []
    for spec in SPECS:
        for code in universe:
            category, detail = _mean_row(
                spec.stat, code, produced.get((spec.feature_id, code)), window, window_data
            )
            counts[category] += 1
            if category == "已裁定":
                counts[f"已裁定:{spec.stat}:{detail}"] += 1
            if category == "其他":
                others.append(f"{spec.feature_id} {code} {detail}")
    print(
        f"[mean] {EXCLUSION_EVENT.isoformat()} window={[d.isoformat() for d in window]} "
        f"all_a={len(universe)} factors={len(SPECS)} 一致={counts['一致']} "
        f"已裁定={counts['已裁定']} 其他={len(others)}"
    )
    for key, n in sorted(counts.items()):
        if key.startswith("已裁定:"):
            print(f"[mean]   {key}={n}")
    print(f"[mean] elapsed={time.perf_counter() - started:.1f}s")
    assert not others, others[:20]
