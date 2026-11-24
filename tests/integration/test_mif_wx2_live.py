"""MIF（``pf_single_mif_1_mean_neg``）与旧仓 wx2 ``stock_mif`` 对拍。

数据来源：本地 PG（all_a 成员、行情、衍生指标换手）只读。旧值与 wx2 支撑数据来自
``tests/golden/market_data/mif/``：

- ``<YYYYMMDD>.json``：一个截面日。``codes`` 为截面日 all_a 成员（升序），``columns.mif`` 与之等长，
  是 wx2 ``stock_mif.mif`` 原样十进制字符串（numeric(10,6)），无行为 null。
- ``wx2_inputs_<YYYYMMDD>.json``：分类核验所需的 wx2 原始数据：
  ``stock_ratio_missing`` 为 wx2 night 窗口内缺 stock_ratio 行或为 NULL 的（日期, 代码）清单；
  ``wx2_window`` 为本地与旧值不等的股票，其 wx2 个股自有 21 行窗口（日期、复权开盘、复权前收、状态、换手、
  stock_ratio.night_ratio 原值）；
  ``cell_diff`` 为登记表：窗口内 wx2 stock_ratio 单元格与本地按裁定 1（4 位 ROUND_HALF_UP）算出的值不同的行；
  ``stale_old`` 为登记表：旧表陈旧的 (日期, 代码, 旧值, wx2 输入算出值)。

截面日来自“可复现区间”，见 ``docs/adr/2026-11-24-mif.md`` 决策 3：截面日的 21 行窗口内，每个交易日的 wx2
``stock_ratio`` 与公式吻合率都 ≥99%。四个 golden 日都在区间内。区间外的截面日不进入本测试。
裁定 1 后按月抽样（每月一个截面日，共 62 个月）：可复现的 51 个抽样日一致率 95.87%–99.65%（并集口径，含停牌），
其中有 9 只股票（8 个抽样日）归为“其他”，未进入 golden，原因见 ADR “未判定”。
(s) 与 (t) 两类只登记，不判定哪一边对。

比对精度按旧表存储精度（numeric(10,6)，ROUND_HALF_UP）。旧表存的是 corr（raw），长表存 ``-raw``，比对前乘回。
每个 (股票, 截面日) 按优先级归入以下一类：

- 一致：双方都有值且相等，或双方都无值。
- 停牌口径差异：旧有值、新无值，本地 night 窗口有 ``trade_status_code == 0`` 的行。wx2 原始 night_ratio 与
  换手按旧 pandas 语义（任一缺失整窗不产值，corr）复现旧值。
- stock_ratio缺行差异：旧无值、新有值，wx2 night 窗口缺 stock_ratio 行（或 NULL）。旧语义在缺行处不产值。
- 源数据差异：wx2 原始窗口（复权价、状态、换手）经本仓同一函数 ``mif_value`` 重算，得到旧值。
- stock_ratio单元格差异（登记为 ``cell_diff``）：wx2 原始 stock_ratio 与换手按新实现的 ``_pearson`` 重算得旧值，
  且窗口内至少一个 stock_ratio 单元格与本地裁定 1 算出的 night_ratio 不同。
  单元格与公式不同的原因未判定：可能是 wx2 派生表单元格本身的误差，也可能是 wx2 复权价与本地不同。
- 旧表陈旧（登记为 ``stale_old``）：wx2 原始输入经 ``mif_value`` 重算不等于旧值，旧语义（pandas 式 corr，
  按 stock_ratio 单元格）也不等于旧值，而本地值等于 wx2 输入重算值。
  旧表与 wx2 原始输入不一致，原因未判定。
- 其他：不属于以上任何一类。测试失败，不加例外。

登记表是硬约束：计算得到的 ``stock_ratio单元格差异`` 与 ``旧表陈旧`` 必须与登记表逐条相等，未登记即失败。
"""

from __future__ import annotations

import functools
import json
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.daily_prices import (
    PostgresDailyPriceRepository,
    load_price_visibility,
)
from quantagent.adapters.postgres.derivative_indicator import PostgresDerivativeIndicatorRepository
from quantagent.adapters.postgres.universe import (
    PostgresUniverseRepository,
    load_derivative_visibility,
)
from quantagent.domain.calendar import open_dates
from quantagent.domain.derivative_indicator.types import Turnover
from quantagent.domain.prices.types import DailyPrice
from quantagent.domain.universe.all_a import ALL_A_UNIVERSE_ID
from quantagent.features.library.price import mif as mif_lib
from quantagent.features.library.price.mif import night_ratio
from quantagent.features.panel.mif import build_mif_values
from quantagent.platform.config import get_settings
from quantagent.platform.pg import connect
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    import psycopg

FIXTURE_DIR = Path(__file__).parents[1] / "golden" / "market_data" / "mif"
GOLDEN_DAYS: tuple[date, ...] = (
    date(2023, 3, 15),
    date(2023, 12, 15),
    date(2024, 5, 15),
    date(2025, 10, 15),
)
AS_OF = date(2026, 11, 24)
COMPUTED_AT = datetime(2026, 11, 24)
EXCHANGE = "SSE"
CALENDAR_PAD_DAYS = 240
# 与 cli/mif_materialize.py 的 _OWN_ROW_PAD_DAYS 一致，本地窗口按这个范围读取。
OWN_ROW_PAD_DAYS = 120
WINDOW = mif_lib.WINDOW
LAG = mif_lib.LAG
SPAN = WINDOW + LAG
Q6 = Decimal("0.000001")

CAT_SAME = "一致"
CAT_BOTH_NONE = "双方无值"
CAT_HALT = "停牌口径差异"
CAT_MISSING = "stock_ratio缺行差异"
CAT_SOURCE = "源数据差异"
CAT_CELL = "stock_ratio单元格差异"
CAT_STALE = "旧表陈旧"
CAT_OTHER = "其他"
CATEGORIES = (
    CAT_SAME,
    CAT_BOTH_NONE,
    CAT_HALT,
    CAT_MISSING,
    CAT_SOURCE,
    CAT_CELL,
    CAT_STALE,
    CAT_OTHER,
)
FAILURE_LIST_LIMIT = 20


@dataclass(frozen=True)
class _Golden:
    day: date
    codes: tuple[str, ...]
    old: dict[str, Decimal | None]
    missing: dict[str, tuple[str, ...]]
    wx2_window: dict[str, dict[str, Any]]
    cell_registry: tuple[dict[str, str], ...]
    stale_registry: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class _DayResult:
    day: date
    counts: Counter[str]
    others: tuple[str, ...]
    scope: int
    wx2_in_scope: int
    local_values: int
    categories: dict[str, str]
    cell_rows: tuple[dict[str, str], ...]
    stale_rows: tuple[dict[str, str], ...]


def _ymd(day: date) -> str:
    return day.strftime("%Y%m%d")


def _q6(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(Q6, rounding=ROUND_HALF_UP)


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _load_golden(day: date) -> _Golden:
    fixture = json.loads((FIXTURE_DIR / f"{_ymd(day)}.json").read_text(encoding="utf-8"))
    support = json.loads((FIXTURE_DIR / f"wx2_inputs_{_ymd(day)}.json").read_text(encoding="utf-8"))
    codes: list[str] = fixture["codes"]
    if codes != sorted(set(codes)) or len(codes) != fixture["provenance"]["scope_count"]:
        raise ValueError(f"fixture {day} 的 codes 不是升序去重或与 scope_count 不符")
    values = fixture["columns"]["mif"]
    if len(values) != len(codes):
        raise ValueError(f"fixture {day} 的 mif 与 codes 长度不等")
    return _Golden(
        day=day,
        codes=tuple(codes),
        old={code: _dec(v) for code, v in zip(codes, values, strict=True)},
        missing={code: tuple(dates) for code, dates in support["stock_ratio_missing"].items()},
        wx2_window=support["wx2_window"],
        cell_registry=tuple(support["cell_diff"]),
        stale_registry=tuple(support["stale_old"]),
    )


def _cells(entry: dict[str, Any]) -> list[Decimal | None]:
    return [_dec(v) for v in entry["night_ratio"]]


def _turns(entry: dict[str, Any]) -> list[Decimal | None]:
    return [_dec(v) for v in entry["turn"]]


@functools.cache
def _contracts() -> tuple[Any, Any]:
    return load_price_visibility(), load_derivative_visibility()


def _legacy_raw(night: Sequence[Decimal | None], turns: Sequence[Decimal | None]) -> Decimal | None:
    """旧仓 pandas 语义：任一缺失整窗不产值；corr 用 numpy 浮点计算，与 pandas 的 Pearson 一致。"""
    if len(night) != WINDOW or len(turns) != WINDOW:
        return None
    if any(v is None for v in night) or any(v is None for v in turns):
        return None
    xs = np.asarray([abs(float(v)) for v in night if v is not None], dtype=float)
    ys = np.asarray([float(v) for v in turns if v is not None], dtype=float)
    if np.all(xs == xs[0]) or np.all(ys == ys[0]):
        return None
    r = float(np.corrcoef(xs, ys)[0, 1])
    return Decimal(repr(r)) if np.isfinite(r) else None


def _cell_raw(entry: dict[str, Any]) -> Decimal | None:
    """wx2 原始 stock_ratio 单元格与 wx2 换手，经新实现的 ``_pearson`` 重算。任一缺失整窗不产值。"""
    nights = _cells(entry)[LAG:]
    turns = _turns(entry)[:WINDOW]
    if any(v is None for v in nights) or any(v is None for v in turns):
        return None
    xs = [abs(v) for v in nights if v is not None]
    ys = [v for v in turns if v is not None]
    return mif_lib._pearson(xs, ys)


def _replaced_raw(code: str, source: dict[str, Any]) -> Decimal | None:
    """wx2 原始 21 行窗口（复权价、状态、换手）经本仓同一函数 ``mif_value`` 重算，返回 raw（corr）。
    night_ratio 由复权价按裁定 1 计算，不读 stock_ratio 单元格。"""
    price_contract, turn_contract = _contracts()
    dates = [datetime.strptime(d, "%Y%m%d").date() for d in source["dates"]]
    prices = [
        DailyPrice(
            trade_dt=dt,
            wind_code=code,
            open=None,
            high=None,
            low=None,
            close=None,
            volume=None,
            amount=None,
            pct_change=None,
            adj_open=_dec(source["adj_open"][i]),
            adj_preclose=_dec(source["adj_preclose"][i]),
            trade_status_code=source["status"][i],
        )
        for i, dt in enumerate(dates)
    ]
    turn_by_day = {
        dt: Turnover(trade_dt=dt, wind_code=code, turnover=_dec(source["turn"][i]))
        for i, dt in enumerate(dates[:WINDOW])
    }
    value = mif_lib.mif_value(
        prices, turn_by_day, price_contract=price_contract, turnover_contract=turn_contract
    )
    return None if value is None else value.raw


class _Context:
    """只读访问本地 PG，并按截面日取本地输入与新实现结果。"""

    def __init__(self) -> None:
        settings = get_settings()
        paths = resolve_var_paths(settings, repo_root=detect_repo_root())
        self.conn: psycopg.Connection[object] = connect(settings, "src")
        self.conn.read_only = True
        self.calendar = LakeCalendarRepository(paths.lake / "std" / "trade_calendar")
        self.universe = PostgresUniverseRepository(self.conn)
        self.prices_repo = PostgresDailyPriceRepository(self.conn)
        self.turn_repo = PostgresDerivativeIndicatorRepository(self.conn)

    def close(self) -> None:
        self.conn.close()

    def all_a(self, day: date) -> frozenset[str]:
        members = self.universe.members_at(as_of=AS_OF, dt=day, universe_id=ALL_A_UNIVERSE_ID)
        return frozenset(member.asset_id for member in members)

    def local(
        self, day: date, codes: tuple[str, ...]
    ) -> tuple[tuple[DailyPrice, ...], tuple[Turnover, ...], dict[str, Decimal]]:
        days = self.calendar.list_days(
            as_of=AS_OF,
            exchange=EXCHANGE,
            start=day - timedelta(days=CALENDAR_PAD_DAYS),
            end=day,
        )
        assert day in set(open_dates(days)), f"{day} 不是开市日"
        start = day - timedelta(days=OWN_ROW_PAD_DAYS)
        prices = self.prices_repo.list_prices(as_of=AS_OF, start=start, end=day, wind_codes=codes)
        turns = self.turn_repo.list_turnover(as_of=AS_OF, start=start, end=day, wind_codes=codes)
        price_contract, turn_contract = _contracts()
        rows = build_mif_values(
            prices,
            turns,
            price_contract=price_contract,
            turnover_contract=turn_contract,
            start=day,
            end=day,
            computed_at=COMPUTED_AT,
            run_id=f"golden-mif-{_ymd(day)}",
        )
        produced: dict[str, Decimal] = {}
        for row in rows:
            assert row.event_dt == day
            # FeatureValue.value 为 float，SIGN=-1，raw = -value；经 repr 还原最短十进制。
            produced[row.asset_id] = -Decimal(repr(row.value))
        return prices, turns, produced


@pytest.fixture(scope="module")
def ctx() -> Iterator[_Context]:
    context = _Context()
    yield context
    context.close()


def _local_windows(prices: Sequence[DailyPrice], day: date) -> dict[str, list[DailyPrice]]:
    by_code: dict[str, list[DailyPrice]] = {}
    for row in prices:
        if row.trade_dt <= day:
            by_code.setdefault(row.wind_code, []).append(row)
    out: dict[str, list[DailyPrice]] = {}
    for code, rows in by_code.items():
        ordered = sorted(rows, key=lambda item: item.trade_dt)
        if len(ordered) >= SPAN:
            out[code] = ordered[-SPAN:]
    return out


def _cell_diff_rows(
    code: str, golden: _Golden, windows: dict[str, list[DailyPrice]]
) -> list[dict[str, str]]:
    """窗口内 wx2 stock_ratio 单元格与本地 night_ratio 不同的行。None 与 None 视为相同。"""
    window = windows.get(code)
    entry = golden.wx2_window.get(code)
    if window is None or entry is None:
        return []
    cells = dict(zip(entry["dates"][LAG:], _cells(entry)[LAG:], strict=True))
    rows: list[dict[str, str]] = []
    for row in window[LAG:]:
        key = _ymd(row.trade_dt)
        if key not in cells:
            continue
        local = night_ratio(row)
        cell = cells[key]
        if cell != local:
            rows.append(
                {
                    "date": key,
                    "code": code,
                    "wx2": "null" if cell is None else format(cell, "f"),
                    "local": "null" if local is None else format(local, "f"),
                }
            )
    return rows


def _classify_missing_old(
    code: str, golden: _Golden, windows: dict[str, list[DailyPrice]]
) -> tuple[str, str]:
    """旧无值、新有值：只有 wx2 night 窗口缺 stock_ratio 行（或 NULL）时才是已解释的缺行差异。"""
    missing = golden.missing.get(code)
    if not missing:
        return CAT_OTHER, "旧无值、wx2 窗口无 stock_ratio 缺行"
    window = windows.get(code)
    night_dates = {_ymd(row.trade_dt) for row in window[LAG:]} if window else set()
    if not set(missing) <= night_dates:
        return CAT_OTHER, "缺行日期不在本地 night 窗口内"
    # 旧语义要求 night 窗口每一行都非空，缺一行即整窗不产值，所以缺行直接解释旧无值。
    return CAT_MISSING, f"缺行 {len(missing)} 个"


def _halt_explains(
    code: str,
    golden: _Golden,
    windows: dict[str, list[DailyPrice]],
    old: Decimal,
) -> tuple[bool, int]:
    """本地 night 窗口有停牌行，且 wx2 原始输入按旧语义复现旧值。返回 (是否成立, 停牌行数)。"""
    window = windows.get(code)
    entry = golden.wx2_window.get(code)
    if window is None or entry is None:
        return False, 0
    halt = sum(1 for row in window[LAG:] if row.trade_status_code == 0)
    if halt == 0:
        return False, 0
    raw = _legacy_raw(_cells(entry)[LAG:], _turns(entry)[:WINDOW])
    return raw is not None and _q6(raw) == old, halt


def _classify(
    code: str,
    golden: _Golden,
    windows: dict[str, list[DailyPrice]],
    old: Decimal | None,
    new: Decimal | None,
) -> tuple[str, str]:
    """返回 (类别, 原因)。old、new 都已按 numeric(10,6) 量化。"""
    if old == new:
        return (CAT_SAME if old is not None else CAT_BOTH_NONE), ""
    if old is None:
        return _classify_missing_old(code, golden, windows)
    if new is None:
        return _classify_missing_new(code, golden, windows, old)
    return _classify_both_present(code, golden, windows, old, new)


def _classify_missing_new(
    code: str,
    golden: _Golden,
    windows: dict[str, list[DailyPrice]],
    old: Decimal,
) -> tuple[str, str]:
    """旧有值、新无值：只有停牌行的旧语义复现才是已解释的停牌口径差异。"""
    if code not in golden.wx2_window:
        return CAT_OTHER, "旧值存在但无 wx2 窗口"
    explained, halt = _halt_explains(code, golden, windows, old)
    if explained:
        return CAT_HALT, f"窗口内停牌行 {halt} 个，旧语义复现"
    return CAT_OTHER, f"old={old} new=None"


def _classify_both_present(
    code: str,
    golden: _Golden,
    windows: dict[str, list[DailyPrice]],
    old: Decimal,
    new: Decimal,
) -> tuple[str, str]:
    """双方都有值且不等：依次检查源数据、单元格、旧表陈旧。"""
    entry = golden.wx2_window.get(code)
    if entry is None:
        return CAT_OTHER, "旧值存在但无 wx2 窗口"
    if _q6(_replaced_raw(code, entry)) == old:
        return CAT_SOURCE, "wx2 原始窗口替换后 mif_value 复现旧值"
    cell = _cell_raw(entry)
    cell_matches_old = cell is not None and _q6(cell) == old
    if cell_matches_old:
        if _cell_diff_rows(code, golden, windows):
            return CAT_CELL, "wx2 stock_ratio 单元格替换后复现旧值，且单元格与本地不同"
        return CAT_OTHER, "单元格复现旧值，但窗口内单元格与本地无差异"
    if _q6(_replaced_raw(code, entry)) == new:
        return CAT_STALE, "wx2 输入经 mif_value 与旧语义都不复现旧值，本地等于 wx2 输入重算值"
    return CAT_OTHER, f"old={old} new={new}"


def _run_day(ctx: _Context, golden: _Golden) -> _DayResult:
    scope = frozenset(golden.codes)
    if ctx.all_a(golden.day) != scope:
        raise AssertionError(f"{golden.day} 的 fixture 范围与当前 all_a 成员不一致")
    prices, _turns, produced = ctx.local(golden.day, golden.codes)
    windows = _local_windows(prices, golden.day)
    counts: Counter[str] = Counter()
    others: list[str] = []
    categories: dict[str, str] = {}
    cell_rows: list[dict[str, str]] = []
    stale_rows: list[dict[str, str]] = []
    for code in golden.codes:
        old = _q6(golden.old[code])
        new = _q6(produced.get(code))
        category, reason = _classify(code, golden, windows, old, new)
        counts[category] += 1
        categories[code] = category
        if category == CAT_OTHER:
            others.append(f"{code} {reason}")
        if category == CAT_CELL:
            cell_rows.extend(_cell_diff_rows(code, golden, windows))
        if category == CAT_STALE:
            entry = golden.wx2_window[code]
            stale_rows.append(
                {
                    "date": _ymd(golden.day),
                    "code": code,
                    "old": format(old, "f") if old is not None else "null",
                    "wx2": format(_q6(_replaced_raw(code, entry)), "f"),
                    "local": format(new, "f") if new is not None else "null",
                }
            )
    return _DayResult(
        day=golden.day,
        counts=counts,
        others=tuple(others),
        scope=len(golden.codes),
        wx2_in_scope=sum(1 for code in golden.codes if golden.old[code] is not None),
        local_values=sum(1 for code in golden.codes if code in produced),
        categories=categories,
        cell_rows=tuple(sorted(cell_rows, key=lambda r: (r["date"], r["code"]))),
        stale_rows=tuple(sorted(stale_rows, key=lambda r: r["code"])),
    )


@pytest.fixture(scope="module")
def results(ctx: _Context) -> dict[date, _DayResult]:
    return {day: _run_day(ctx, _load_golden(day)) for day in GOLDEN_DAYS}


def _as_key(row: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(row.items()))


@pytest.mark.integration
@pytest.mark.parametrize("day", GOLDEN_DAYS, ids=lambda d: d.isoformat())
def test_mif_matches_wx2_with_explained_differences_only(
    results: dict[date, _DayResult], day: date
) -> None:
    result = results[day]
    print(
        f"\n[{day.isoformat()}] scope={result.scope} wx2_in_scope={result.wx2_in_scope} "
        f"local={result.local_values} "
        + " ".join(f"{name}={result.counts.get(name, 0)}" for name in CATEGORIES)
    )
    assert not result.counts.get(CAT_OTHER, 0), list(result.others[:FAILURE_LIST_LIMIT])


@pytest.mark.integration
@pytest.mark.parametrize("day", GOLDEN_DAYS, ids=lambda d: d.isoformat())
def test_cell_diff_registry_is_complete_and_exact(
    results: dict[date, _DayResult], day: date
) -> None:
    """stock_ratio单元格差异的登记表必须与计算结果逐条相等，且每条都是 wx2 单元格与本地真实不同。"""
    golden = _load_golden(day)
    computed = {_as_key(row) for row in results[day].cell_rows}
    registered = {_as_key(row) for row in golden.cell_registry}
    assert computed == registered, (
        sorted(computed - registered)[:FAILURE_LIST_LIMIT],
        sorted(registered - computed)[:FAILURE_LIST_LIMIT],
    )
    for row in golden.cell_registry:
        assert row["wx2"] != row["local"], row


@pytest.mark.integration
@pytest.mark.parametrize("day", GOLDEN_DAYS, ids=lambda d: d.isoformat())
def test_stale_registry_is_complete_and_exact(results: dict[date, _DayResult], day: date) -> None:
    """旧表陈旧的登记表必须与计算结果逐条相等。每条：旧值 ≠ wx2 输入重算值，本地值 = wx2 输入重算值。"""
    golden = _load_golden(day)
    computed = {_as_key(row) for row in results[day].stale_rows}
    registered = {_as_key(row) for row in golden.stale_registry}
    assert computed == registered, (
        sorted(computed - registered)[:FAILURE_LIST_LIMIT],
        sorted(registered - computed)[:FAILURE_LIST_LIMIT],
    )
    for row in golden.stale_registry:
        assert row["old"] != row["wx2"], row
        assert row["local"] == row["wx2"], row


@pytest.mark.integration
@pytest.mark.parametrize("day", GOLDEN_DAYS, ids=lambda d: d.isoformat())
def test_source_difference_requires_wx2_window_to_differ_from_local(
    ctx: _Context, results: dict[date, _DayResult], day: date
) -> None:
    """归入源数据差异的股票，wx2 原始窗口必须与本地窗口不同。否则它不构成证据。"""
    golden = _load_golden(day)
    prices, turns, _ = ctx.local(day, golden.codes)
    windows = _local_windows(prices, day)
    local_turn = {(t.wind_code, _ymd(t.trade_dt)): t.turnover for t in turns}
    for code, category in results[day].categories.items():
        if category != CAT_SOURCE:
            continue
        entry = golden.wx2_window[code]
        window = windows.get(code)
        if window is None:
            continue
        same_dates = [_ymd(row.trade_dt) for row in window] == entry["dates"]
        same_prices = all(
            (_dec(entry["adj_open"][i]), _dec(entry["adj_preclose"][i]), entry["status"][i])
            == (row.adj_open, row.adj_preclose, row.trade_status_code)
            for i, row in enumerate(window)
        )
        same_turn = all(
            _dec(entry["turn"][i]) == local_turn.get((code, _ymd(row.trade_dt)))
            for i, row in enumerate(window[:WINDOW])
        )
        assert not (same_dates and same_prices and same_turn), (code, day)
