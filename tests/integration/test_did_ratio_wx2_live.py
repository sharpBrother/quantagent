"""稳健股息率 ``did_ratio_realized_1`` 与旧仓 wx2 ``stock_did_ratio.did_ratio_realized_1`` 对拍。

数据来源：本地 PG（股票域、分红、利润表、财务指标、市值，只读）。旧值与 wx2 原始行来自
``tests/golden/market_data/did_ratio/``：

- ``<YYYYMMDD>.json``：一个截面日的列式 fixture。``codes`` 为截面日股票域（all_a 去掉当日 ST，升序），
  ``old`` 与之等长，是 wx2 原样十进制字符串或 null。``provenance`` 记录域外旧行数（只计数，不比对）。
  ``categories`` 为登记表：每个 (代码) 非“一致”时的类别。
- ``wx2_inputs_<YYYYMMDD>.json``：非一致股票的 wx2 原始行（分红、利润表、财务指标、市值），
  按 ``ANN_DT ∈ (T − 1825 天, T]`` 且季末报告期裁剪，与旧 SQL 窗口一致。

每个 (股票, 截面日) 按优先级归入以下一类，其他必须为 0：

- 一致：双方取值相等（含双方都无值）。
- 同键冲突跳过：本地同一 (代码, 报告期, 公告日) 有两个不同取值。裁定 1：跳过该股该日，不猜。
- 情形 C：旧代码近 3 年没有盈利年份，``min(80, NaN) = 80`` 使派息率变成 80%。修正后为 0。
- TTM 为空：本地与 wx2 原始行的最新 TTM 都为空，旧值等于未封顶的 realized。裁定 2：新实现不产值。
- 修订取舍：同报告期有多条修订，旧值等于取较早公告的重算值，新值等于取最大公告日的重算值。裁定 4。
- 源数据差异：wx2 原始行经本仓同一函数重算得旧值，本地输入行与 wx2 不同（含 wx2 独有行，即源端漏行）。
  wx2 原始行同键有两个不同取值、本地只保留其一的，取本地没有的那个重算（如 300379.SZ）。
- 旧表陈旧：wx2 原始行按新口径重算不等于旧值，旧语义也不等于旧值，本地值等于 wx2 原始行重算值。
  旧表与 wx2 原始行不一致，原因未判定。
- 其他：不属于以上任何一类。测试失败，不加例外。

旧语义在本测试中单独转写为 ``_legacy``，不依赖 pandas，也不依赖仓库外的旧仓代码。
它只复现旧 ``factor_fundamental.py`` 的 ``did_ratio_realized_1`` 分支，同报告期取舍由参数指定。
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import pytest

from quantagent.adapters.postgres.derivative_indicator import PostgresDerivativeIndicatorRepository
from quantagent.adapters.postgres.fundamental import (
    DIVIDEND_DATASET,
    INCOME_DATASET,
    INDICATOR_DATASET,
    PostgresDividendRepository,
    PostgresFinancialIndicatorRepository,
    PostgresNetProfitRepository,
    load_fundamental_visibility,
)
from quantagent.adapters.postgres.st import PostgresStStatusRepository
from quantagent.adapters.postgres.universe import load_derivative_visibility
from quantagent.cli._universe import all_a_members_by_day
from quantagent.domain.fundamental.types import DividendRecord, IndicatorRecord, NetProfitRecord
from quantagent.features.library.fundamental import did_ratio as dr
from quantagent.features.panel.did_ratio import build_did_ratio_values
from quantagent.platform.config import get_settings
from quantagent.platform.pg import connect

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    import psycopg

FIXTURE_DIR = Path(__file__).parents[1] / "golden" / "market_data" / "did_ratio"

# 四个 golden 截面日。区间外的截面日不进入本测试，见 docs/adr/2026-11-25-did-ratio.md。
GOLDEN_DAYS: tuple[date, ...] = (
    date(2023, 3, 15),
    date(2023, 12, 15),
    date(2024, 5, 15),
    date(2025, 10, 15),
)
# 只决定可见性截止（PIT），窗口本身由截面日限定，取不早于所有截面日的日期即可。
AS_OF = date(2026, 11, 25)
Q6 = Decimal("0.000001")
QUARTER_ENDS = frozenset({(3, 31), (6, 30), (9, 30), (12, 31)})
# 季末的上一个季末。一季报的上一期是上年年报，与旧代码 ``get_last_period`` 一致。
PREV_QUARTER_END: dict[int, tuple[int, int]] = {3: (12, 31), 6: (3, 31), 9: (6, 30), 12: (9, 30)}

CAT_SAME = "一致"
CAT_CONFLICT = "同键冲突跳过"
CAT_C = "情形C"
CAT_TTM = "TTM为空"
CAT_REVISION = "修订取舍"
CAT_SOURCE = "源数据差异"
CAT_STALE = "旧表陈旧"
CAT_OTHER = "其他"
CATEGORIES = (
    CAT_SAME,
    CAT_CONFLICT,
    CAT_C,
    CAT_TTM,
    CAT_REVISION,
    CAT_SOURCE,
    CAT_STALE,
    CAT_OTHER,
)
FAILURE_LIST_LIMIT = 20


class _Ambiguous(Exception):
    """同一报告期在选中的公告日有两个不同取值，旧语义无法判定取哪一个。"""


class _Conflict:
    """本仓同键冲突（``DidRatioConflictError``）的哨兵值。"""


CONFLICT = _Conflict()


@dataclass(frozen=True)
class Raw:
    """一只股票在窗口内的输入行。日期为 ``date``，取值为 ``Decimal``，缺值为 ``None``。

    ``div`` 与 ``inc`` 的元素为 (公告日, 报告期, 值)；``ind`` 的元素为 (公告日, 报告期)；
    ``mv`` 为 T 当日 ``S_VAL_MV``，单位万元。
    """

    div: tuple[tuple[date, date, Decimal | None], ...]
    inc: tuple[tuple[date, date, Decimal | None], ...]
    ind: tuple[tuple[date, date], ...]
    mv: Decimal | None


@dataclass(frozen=True)
class Old:
    """旧语义的一次重算。``ttm`` 与 ``payout`` 为空时分别表示没有最新 TTM、没有盈利年份。"""

    value: Decimal | None
    ttm: Decimal | None
    realized: Decimal | None
    payout: Decimal | None


_NO_OLD = Old(value=None, ttm=None, realized=None, payout=None)


def _ymd(day: date) -> str:
    return day.strftime("%Y%m%d")


def _ymd_date(text: str) -> date:
    return datetime.strptime(text, "%Y%m%d").date()


def q6(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(Q6, rounding=ROUND_HALF_UP)


def _text(value: Decimal | _Conflict | None) -> str:
    """登记表中的十进制文本，缺值为 ``null``。"""
    if isinstance(value, _Conflict):
        raise AssertionError("登记的取值不应为冲突")
    return "null" if value is None else format(value, "f")


def _from_float(value: float | None) -> Decimal | None:
    # FeatureValue.value 为 float。经 repr 还原最短十进制，再按 6 位舍入。
    return None if value is None else q6(Decimal(repr(value)))


def _is_qend(report: date) -> bool:
    return (report.month, report.day) in QUARTER_ENDS


def _in_window(day: date, ann: date, report: date) -> bool:
    lower = day - timedelta(days=dr.WINDOW_DAYS)
    return lower < ann <= day and _is_qend(report)


def _window_rows(day: date, raw: Raw) -> tuple[list[Any], list[Any], list[Any]]:
    divs = [row for row in raw.div if _in_window(day, row[0], row[1])]
    incs = [row for row in raw.inc if _in_window(day, row[0], row[1])]
    inds = [row for row in raw.ind if _in_window(day, row[0], row[1])]
    return divs, incs, inds


def _pick_by_revision(
    rows: Sequence[tuple[date, date, Decimal | None]],
    revision: Literal["max", "min"],
) -> dict[date, Decimal | None]:
    """每个报告期取 ANN_DT 最大（或最小）的一条。选中的公告日内取值不一致则放弃，不猜。"""
    by_report: dict[date, list[tuple[date, Decimal | None]]] = {}
    for ann, report, value in rows:
        by_report.setdefault(report, []).append((ann, value))
    out: dict[date, Decimal | None] = {}
    for report, items in by_report.items():
        picked = max(a for a, _ in items) if revision == "max" else min(a for a, _ in items)
        values = {v for a, v in items if a == picked}
        if len(values) != 1:
            raise _Ambiguous(report.isoformat())
        out[report] = values.pop()
    return out


def _quarter_values(points: Sequence[tuple[date, Decimal | None]]) -> list[Decimal | None]:
    """单季值，复现 ``RAW._add_quarter_col``。上一条不是紧邻的上一季末时为空。"""
    out: list[Decimal | None] = []
    for index, (report, value) in enumerate(points):
        if index == 0:
            out.append(None)
            continue
        prev_report, prev_value = points[index - 1]
        month, day = PREV_QUARTER_END[report.month]
        expected = date(report.year - 1 if report.month == 3 else report.year, month, day)
        if prev_report != expected:
            out.append(None)
        elif report.month == 3:
            out.append(value)
        else:
            out.append(None if value is None or prev_value is None else value - prev_value)
    return out


def _ttm(points: Sequence[tuple[date, Decimal | None]]) -> Decimal | None:
    """最新一条的 TTM。年报直接取年度值；其他取最近四个单季之和，任一为空则为空。"""
    if not points:
        return None
    report, value = points[-1]
    if report.month == 12:
        return value
    quarters = _quarter_values(points)
    if len(quarters) < 4:
        return None
    tail = quarters[-4:]
    if any(item is None for item in tail):
        return None
    return sum((item for item in tail if item is not None), Decimal(0))


def _legacy(day: date, raw: Raw, revision: Literal["max", "min"]) -> Old:
    """旧代码 ``did_ratio_realized_1`` 的重算。缺输入、缺市值时不产值。

    与旧代码的差异只有两处，都是旧语义本身：``min(80, NaN) = 80``，以及 TTM 为空时退回 realized 不封顶。
    同报告期取舍由 ``revision`` 指定，旧 SQL 的 keep-last 顺序没有保证，只能用两端检验。
    """
    divs, incs, inds = _window_rows(day, raw)
    if not inds or not incs or raw.mv is None:
        return _NO_OLD
    try:
        dv = _pick_by_revision(divs, revision)
        pf = _pick_by_revision(incs, revision)
    except _Ambiguous:
        return _NO_OLD
    dv_points = sorted((report, value) for report, value in dv.items() if value is not None)
    if not dv_points:
        return Old(value=Decimal(0), ttm=None, realized=None, payout=None)
    lst = max(dv_points[-1][0], date(day.year - 2, 12, 31))
    cutoff = date(lst.year - 2, 1, 1)
    divs_cut = [(report, value) for report, value in dv_points if report >= cutoff]
    if not divs_cut:
        return Old(value=Decimal(0), ttm=None, realized=None, payout=None)
    last_div = divs_cut[-1][0]
    profit_points = sorted(pf.items())
    ttm = _ttm(profit_points)
    incs_cut = [(report, value) for report, value in profit_points if cutoff <= report <= last_div]
    mv_yuan = raw.mv * Decimal(10000)
    total = sum((value for _, value in divs_cut if value is not None), Decimal(0))
    realized = Decimal(100) * total / mv_yuan / (Decimal(2 * 12 + lst.month) / Decimal(12))
    years = (lst.year - 2, lst.year - 1, lst.year)
    did_by_year = {y: Decimal(0) for y in years}
    for report, value in divs_cut:
        if report.year in did_by_year and value is not None:
            did_by_year[report.year] += value
    inc_by_year: dict[int, Decimal | None] = {}
    for inc_report, inc_value in incs_cut:
        inc_by_year[inc_report.year] = inc_value
    positive = [y for y in years if (inc_by_year.get(y) or Decimal(0)) > 0]
    payout: Decimal | None = None
    if positive:
        payout = (
            Decimal(100)
            * sum((did_by_year[y] for y in positive), Decimal(0))
            / sum((inc_by_year[y] or Decimal(0) for y in positive), Decimal(0))
        )
    payout_eff = Decimal(80) if payout is None else min(payout, Decimal(80))
    if ttm is None:
        value = realized
    elif ttm <= 0:
        value = min(realized, Decimal(0))
    else:
        value = min(realized, payout_eff / (mv_yuan / ttm))
    return Old(value=value, ttm=ttm, realized=realized, payout=payout)


def _records(code: str, raw: Raw) -> tuple[list[Any], list[Any], list[Any]]:
    divs = [
        DividendRecord(asset_id=code, ann_dt=a, report_period=r, tot_cash_dvd=v)
        for a, r, v in raw.div
    ]
    incs = [
        NetProfitRecord(asset_id=code, ann_dt=a, report_period=r, net_profit_after_ded=v)
        for a, r, v in raw.inc
    ]
    inds = [IndicatorRecord(asset_id=code, ann_dt=a, report_period=r) for a, r in raw.ind]
    return divs, incs, inds


def lib_value(day: date, code: str, raw: Raw) -> Decimal | _Conflict | None:
    """本仓 ``did_ratio_realized_1`` 在给定输入上的取值，经 6 位舍入。"""
    divs, incs, inds = _records(code, raw)
    try:
        value = dr.did_ratio_realized_1(
            as_of=day,
            dividends=divs,
            net_profits=incs,
            indicators=inds,
            market_value=raw.mv,
        )
    except dr.DidRatioConflictError:
        return CONFLICT
    return None if value is None else _from_float(float(value))


def _resolve_against_local(wx: Raw, local: Raw) -> Raw | None:
    """wx2 原始行同键有两个不同取值、且本地只保留其中一个时，改取本地没有的那个，得到 wx2 独有版本。

    只处理利润表与分红中“一个键两个取值、本地恰好有其一”的情形。不适用返回 ``None``。
    """

    def fix(rows: tuple[tuple[date, date, Decimal | None], ...], local_rows: Any) -> Any:
        by_key: dict[tuple[date, date], set[Decimal | None]] = {}
        for ann, report, value in rows:
            by_key.setdefault((ann, report), set()).add(value)
        local_by_key: dict[tuple[date, date], set[Decimal | None]] = {}
        for ann, report, value in local_rows:
            local_by_key.setdefault((ann, report), set()).add(value)
        out: list[tuple[date, date, Decimal | None]] = []
        for ann, report, value in rows:
            values = by_key[(ann, report)]
            if len(values) == 1:
                out.append((ann, report, value))
                continue
            local_values = local_by_key.get((ann, report), set())
            if len(local_values) != 1 or not local_values <= values:
                raise _Ambiguous(f"{report} {ann}")
            (kept,) = local_values
            others = values - {kept}
            if len(others) != 1:
                raise _Ambiguous(f"{report} {ann}")
            if value == kept:
                out.append((ann, report, others.pop()))
            else:
                out.append((ann, report, value))
        return tuple(out)

    try:
        div = fix(wx.div, local.div)
        inc = fix(wx.inc, local.inc)
    except _Ambiguous:
        return None
    return Raw(div=div, inc=inc, ind=wx.ind, mv=wx.mv)


def wx_value(day: date, code: str, wx: Raw, local: Raw) -> tuple[Decimal | _Conflict | None, bool]:
    """wx2 原始行经本仓重算的取值。返回 (取值, 是否经过本地对照解析)。

    wx2 原始行本身无同键冲突时直接重算。有冲突时，只有“本地恰好保留其中一个取值”才解析，否则仍为冲突。
    """
    direct = lib_value(day, code, wx)
    if direct is not CONFLICT:
        return direct, False
    resolved = _resolve_against_local(wx, local)
    if resolved is None:
        return CONFLICT, False
    value = lib_value(day, code, resolved)
    return value, value is not CONFLICT


def _wx_only_keys_match_local(wx: Raw, local: Raw) -> bool:
    """wx2 同键两个不同取值的，本地只保留其中一个。没有这类键时为真。"""
    for rows, local_rows in ((wx.div, local.div), (wx.inc, local.inc)):
        wx_keys: dict[tuple[date, date], set[Decimal | None]] = {}
        for ann, report, value in rows:
            wx_keys.setdefault((ann, report), set()).add(value)
        local_keys: dict[tuple[date, date], set[Decimal | None]] = {}
        for ann, report, value in local_rows:
            local_keys.setdefault((ann, report), set()).add(value)
        for key, values in wx_keys.items():
            if len(values) > 1 and len(local_keys.get(key, set())) != 1:
                return False
    return True


def _c_ref(day: date, wx: Raw, old: Decimal) -> Old | None:
    """取舍规则 max 或 min 下，近 3 年无盈利年份（派息率为空）、TTM 为正、旧值等于旧语义重算的那一个。"""
    for rule in ("max", "min"):
        ref = _legacy(day, wx, rule)
        if (
            ref.payout is None
            and ref.ttm is not None
            and ref.ttm > 0
            and ref.value is not None
            and old == q6(ref.value)
        ):
            return ref
    return None


def _ttm_empty_ref(day: date, wx: Raw, old: Decimal) -> Old | None:
    """取舍规则 max 或 min 下，最新 TTM 为空且旧值等于未封顶 realized 的那一个重算。没有则为 None。"""
    for rule in ("max", "min"):
        ref = _legacy(day, wx, rule)
        if ref.ttm is None and ref.realized is not None and old == q6(ref.realized):
            return ref
    return None


def _same_key_conflict(raw: Raw, day: date) -> bool:
    """窗口内同 (报告期, 公告日) 有两个不同取值。分红与利润表都检查。"""
    divs, incs, _ = _window_rows(day, raw)
    for rows in (divs, incs):
        seen: dict[tuple[date, date], set[Decimal | None]] = {}
        for ann, report, value in rows:
            seen.setdefault((report, ann), set()).add(value)
        if any(len(values) > 1 for values in seen.values()):
            return True
    return False


def classify(
    day: date,
    code: str,
    *,
    old: Decimal | None,
    new: Decimal | None,
    conflict: bool,
    local: Raw,
    wx: Raw | None,
) -> tuple[str, str]:
    """返回 (类别, 原因)。old、new 都已按 6 位舍入。冲突优先于一致，因为冲突跳过的股票不产值。"""
    if conflict:
        return CAT_CONFLICT, "本地同键同公告日取值不同"
    if old == new:
        return CAT_SAME, ""
    if wx is None:
        return CAT_OTHER, "缺 wx2 原始行"
    return _classify_against_wx(day, code, old=old, new=new, local=local, wx=wx)


def _classify_against_wx(
    day: date,
    code: str,
    *,
    old: Decimal | None,
    new: Decimal | None,
    local: Raw,
    wx: Raw,
) -> tuple[str, str]:
    """旧值与新值不等、且有 wx2 原始行时的分类。顺序：情形 C、TTM 为空、修订取舍、源数据差异、旧表陈旧。"""
    ref_max = _legacy(day, wx, "max")
    ref_min = _legacy(day, wx, "min")
    old_max = q6(ref_max.value)
    old_min = q6(ref_min.value)
    if old is not None and new == Decimal(0) and _c_ref(day, wx, old) is not None:
        return CAT_C, "wx2 原始行按旧语义（NaN 派息率取 80）复现旧值，修正后为 0"
    if (
        old is not None
        and _ttm_empty_ref(day, wx, old) is not None
        and new is None
        and _legacy(day, local, "max").ttm is None
    ):
        return CAT_TTM, "最新 TTM 为空，旧值等于未封顶的 realized（取舍规则 max 或 min）"
    wx_new, resolved = wx_value(day, code, wx, local)
    if old is not None and old == old_min and old != old_max and new is not None and wx_new == new:
        return CAT_REVISION, "旧值为较早公告的重算值，新值为最大公告日的重算值"
    if wx_new is not CONFLICT and wx_new is not None and wx_new == old and new != old:
        reason = (
            "wx2 同键两个取值、本地只保留其一，取本地没有的那个重算得旧值"
            if resolved
            else "wx2 原始行经本仓重算得旧值，本地输入行不同"
        )
        return CAT_SOURCE, reason
    if wx_new is not CONFLICT and new == wx_new and old not in (wx_new, old_max, old_min):
        return CAT_STALE, "wx2 原始行按新口径重算不等于旧值，本地等于该重算值"
    return CAT_OTHER, f"old={old} new={new} wx_new={wx_new}"


@dataclass(frozen=True)
class _Golden:
    day: date
    codes: tuple[str, ...]
    old: dict[str, Decimal | None]
    registry: dict[str, str]
    stale_registry: tuple[dict[str, str], ...]
    wx: dict[str, Raw]
    provenance: dict[str, Any]


@dataclass(frozen=True)
class _DayResult:
    day: date
    counts: Counter[str]
    others: tuple[str, ...]
    computed: dict[str, str]
    new: dict[str, Decimal | None]
    stale_rows: tuple[dict[str, str], ...]
    local_values: int
    local_raw: dict[str, Raw]
    conflicts: frozenset[str]


def _raw_from_json(entry: dict[str, Any]) -> Raw:
    def dec(text: str | None) -> Decimal | None:
        return None if text is None else Decimal(text)

    return Raw(
        div=tuple((_ymd_date(a), _ymd_date(r), dec(v)) for a, r, v in entry["div"]),
        inc=tuple((_ymd_date(a), _ymd_date(r), dec(v)) for a, r, v in entry["inc"]),
        ind=tuple((_ymd_date(a), _ymd_date(r)) for a, r in entry["ind"]),
        mv=None if entry["mv"] is None else Decimal(entry["mv"]),
    )


def _load_golden(day: date) -> _Golden:
    fixture = json.loads((FIXTURE_DIR / f"{_ymd(day)}.json").read_text(encoding="utf-8"))
    support = json.loads((FIXTURE_DIR / f"wx2_inputs_{_ymd(day)}.json").read_text(encoding="utf-8"))
    codes: list[str] = fixture["codes"]
    if codes != sorted(set(codes)):
        raise ValueError(f"fixture {day} 的 codes 不是升序去重")
    values: list[str | None] = fixture["columns"]["did_ratio_realized_1"]
    if len(values) != len(codes):
        raise ValueError(f"fixture {day} 的 did_ratio_realized_1 与 codes 长度不等")
    return _Golden(
        day=day,
        codes=tuple(codes),
        old={
            code: None if v is None else Decimal(v) for code, v in zip(codes, values, strict=True)
        },
        registry=dict(support["categories"]),
        stale_registry=tuple(support["stale"]),
        wx={code: _raw_from_json(entry) for code, entry in support["raw"].items()},
        provenance=fixture["provenance"],
    )


def _pg_raw(conn: psycopg.Connection[object], day: date, codes: tuple[str, ...]) -> dict[str, Raw]:
    """本地 PG 的窗口输入行，按代码分组。只读。"""
    start = day - timedelta(days=dr.WINDOW_DAYS - 1)
    dividends = PostgresDividendRepository(conn).list_dividends(
        as_of=AS_OF, start=start, end=day, wind_codes=codes
    )
    incomes = PostgresNetProfitRepository(conn).list_net_profits(
        as_of=AS_OF,
        start=start,
        end=day,
        statement_type=dr.STATEMENT_TYPE,
        wind_codes=codes,
    )
    indicators = PostgresFinancialIndicatorRepository(conn).list_indicator_rows(
        as_of=AS_OF, start=start, end=day, wind_codes=codes
    )
    market = PostgresDerivativeIndicatorRepository(conn).list_market_value(
        as_of=AS_OF, start=day, end=day, wind_codes=codes
    )
    mv = {row.wind_code: row.total_mv for row in market}
    grouped: dict[str, dict[str, list[Any]]] = {
        code: {"div": [], "inc": [], "ind": []} for code in codes
    }
    for div_row in dividends:
        grouped[div_row.asset_id]["div"].append(
            (div_row.ann_dt, div_row.report_period, div_row.tot_cash_dvd)
        )
    for inc_row in incomes:
        grouped[inc_row.asset_id]["inc"].append(
            (inc_row.ann_dt, inc_row.report_period, inc_row.net_profit_after_ded)
        )
    for ind_row in indicators:
        grouped[ind_row.asset_id]["ind"].append((ind_row.ann_dt, ind_row.report_period))
    out: dict[str, Raw] = {}
    for code in codes:
        items = grouped[code]
        out[code] = Raw(
            div=tuple(items["div"]),
            inc=tuple(items["inc"]),
            ind=tuple(items["ind"]),
            mv=mv.get(code),
        )
    return out


class _Context:
    """只读访问本地 PG，按截面日取股票域与本地计算结果。"""

    def __init__(self) -> None:
        settings = get_settings()
        self.conn: psycopg.Connection[object] = connect(settings, "src")
        self.conn.read_only = True
        self.st = PostgresStStatusRepository(self.conn)

    def close(self) -> None:
        self.conn.close()

    def domain(self, day: date) -> tuple[str, ...]:
        members = all_a_members_by_day(self.conn, as_of=AS_OF, days=(day,))[day]
        return tuple(sorted(members - self.st.st_codes_at(as_of=AS_OF, dt=day)))

    def local(
        self, day: date, codes: tuple[str, ...]
    ) -> tuple[dict[str, Decimal | None], frozenset[str], dict[str, Raw]]:
        """本地新实现的取值（6 位舍入）、同键冲突代码、本地输入行。"""
        raw = _pg_raw(self.conn, day, codes)
        built = build_did_ratio_values(
            domain_by_day={day: frozenset(codes)},
            dividends=[
                DividendRecord(asset_id=c, ann_dt=a, report_period=r, tot_cash_dvd=v)
                for c, rr in raw.items()
                for a, r, v in rr.div
            ],
            net_profits=[
                NetProfitRecord(asset_id=c, ann_dt=a, report_period=r, net_profit_after_ded=v)
                for c, rr in raw.items()
                for a, r, v in rr.inc
            ],
            indicators=[
                IndicatorRecord(asset_id=c, ann_dt=a, report_period=r)
                for c, rr in raw.items()
                for a, r in rr.ind
            ],
            market_values=_market_values(self.conn, day, codes),
            dividend_contract=load_fundamental_visibility(DIVIDEND_DATASET),
            income_contract=load_fundamental_visibility(INCOME_DATASET),
            indicator_contract=load_fundamental_visibility(INDICATOR_DATASET),
            market_contract=load_derivative_visibility(),
            computed_at=datetime(2026, 11, 25),
            run_id=f"golden-did-ratio-{_ymd(day)}",
        )
        values = {row.asset_id: _from_float(row.value) for row in built.values}
        conflicts = frozenset(item.asset_id for item in built.conflicts)
        return {code: values.get(code) for code in codes}, conflicts, raw


def _market_values(
    conn: psycopg.Connection[object], day: date, codes: tuple[str, ...]
) -> list[Any]:
    return list(
        PostgresDerivativeIndicatorRepository(conn).list_market_value(
            as_of=AS_OF, start=day, end=day, wind_codes=codes
        )
    )


@pytest.fixture(scope="module")
def ctx() -> Iterator[_Context]:
    context = _Context()
    yield context
    context.close()


def _run_day(ctx: _Context, golden: _Golden) -> _DayResult:
    domain = ctx.domain(golden.day)
    if domain != golden.codes:
        raise AssertionError(f"{golden.day} 的 fixture 股票域与当前 all_a 去 ST 不一致")
    new, conflicts, local_raw = ctx.local(golden.day, golden.codes)
    counts: Counter[str] = Counter()
    others: list[str] = []
    computed: dict[str, str] = {}
    stale_rows: list[dict[str, str]] = []
    for code in golden.codes:
        old = golden.old[code]
        category, reason = classify(
            golden.day,
            code,
            old=q6(old),
            new=new[code],
            conflict=code in conflicts,
            local=local_raw[code],
            wx=golden.wx.get(code),
        )
        counts[category] += 1
        if category != CAT_SAME:
            computed[code] = category
        if category == CAT_OTHER:
            others.append(f"{code} {reason}")
        if category == CAT_STALE:
            wx_value_, _ = wx_value(golden.day, code, golden.wx[code], local_raw[code])
            stale_rows.append(
                {
                    "date": _ymd(golden.day),
                    "code": code,
                    "old": _text(q6(old)),
                    "wx2": _text(wx_value_),
                    "local": _text(new[code]),
                }
            )
    return _DayResult(
        day=golden.day,
        counts=counts,
        others=tuple(others),
        computed=computed,
        new=new,
        stale_rows=tuple(sorted(stale_rows, key=lambda r: r["code"])),
        local_values=sum(1 for code in golden.codes if new[code] is not None),
        local_raw=local_raw,
        conflicts=conflicts,
    )


@pytest.fixture(scope="module")
def results(ctx: _Context) -> dict[date, _DayResult]:
    return {day: _run_day(ctx, _load_golden(day)) for day in GOLDEN_DAYS}


def _rows_set(raw: Raw, day: date) -> tuple[frozenset[Any], frozenset[Any], frozenset[Any]]:
    divs, incs, inds = _window_rows(day, raw)
    return frozenset(divs), frozenset(incs), frozenset(inds)


@pytest.mark.integration
@pytest.mark.parametrize("day", GOLDEN_DAYS, ids=lambda d: d.isoformat())
def test_did_ratio_matches_wx2_with_explained_differences_only(
    results: dict[date, _DayResult], day: date
) -> None:
    result = results[day]
    print(
        f"\n[{day.isoformat()}] local_values={result.local_values} "
        + " ".join(f"{name}={result.counts.get(name, 0)}" for name in CATEGORIES)
    )
    assert not result.counts.get(CAT_OTHER, 0), list(result.others[:FAILURE_LIST_LIMIT])


@pytest.mark.integration
@pytest.mark.parametrize("day", GOLDEN_DAYS, ids=lambda d: d.isoformat())
def test_category_registry_is_complete_and_exact(
    results: dict[date, _DayResult], day: date
) -> None:
    golden = _load_golden(day)
    computed = results[day].computed
    assert computed == golden.registry, sorted(
        set(computed.items()) ^ set(golden.registry.items())
    )[:FAILURE_LIST_LIMIT]


@pytest.mark.integration
@pytest.mark.parametrize("day", GOLDEN_DAYS, ids=lambda d: d.isoformat())
def test_stale_registry_is_complete_and_exact(results: dict[date, _DayResult], day: date) -> None:
    """旧表陈旧逐行登记（旧值、wx2 原始行重算值、本地值）。登记表必须与计算结果逐条相等。

    每条：旧值 ≠ wx2 原始行重算值，且本地值 = wx2 原始行重算值。
    """
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


def _as_key(row: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(row.items()))


@pytest.mark.integration
@pytest.mark.parametrize("day", GOLDEN_DAYS, ids=lambda d: d.isoformat())
def test_same_key_conflicts_are_real_and_skipped(
    results: dict[date, _DayResult], day: date
) -> None:
    """裁定 1：同 (代码, 报告期, 公告日) 取值不同的，本地必须有多条原始行，且该股该日不产值。"""
    result = results[day]
    conflict_codes = {code for code, cat in result.computed.items() if cat == CAT_CONFLICT}
    assert conflict_codes == set(result.conflicts)
    for code in conflict_codes:
        assert _same_key_conflict(result.local_raw[code], day), code
        assert result.new[code] is None, code


@pytest.mark.integration
@pytest.mark.parametrize("day", GOLDEN_DAYS, ids=lambda d: d.isoformat())
def test_category_rows_satisfy_their_definition(results: dict[date, _DayResult], day: date) -> None:
    """逐行核验：每个非一致类别的行都满足该类别的定义。"""
    golden = _load_golden(day)
    result = results[day]
    failures: list[str] = []
    for code, category in result.computed.items():
        if category in (CAT_CONFLICT, CAT_OTHER):
            continue
        old = q6(golden.old[code])
        wx = golden.wx[code]
        local = result.local_raw[code]
        ref_max = _legacy(day, wx, "max")
        ref_min = _legacy(day, wx, "min")
        wx_new, _ = wx_value(day, code, wx, local)
        local_new = result.new[code]
        if category == CAT_C:
            ok = old is not None and _c_ref(day, wx, old) is not None and local_new == Decimal(0)
        elif category == CAT_TTM:
            ok = (
                old is not None
                and _ttm_empty_ref(day, wx, old) is not None
                and local_new is None
                and _legacy(day, local, "max").ttm is None
            )
        elif category == CAT_REVISION:
            ok = (
                old == q6(ref_min.value)
                and old != q6(ref_max.value)
                and local_new == q6(ref_max.value)
                and local_new == wx_new
                and wx_new is not None
            )
        elif category == CAT_SOURCE:
            ok = (
                wx_new == old
                and local_new != old
                and _rows_set(local, day) != _rows_set(wx, day)
                and _wx_only_keys_match_local(wx, local)
            )
        elif category == CAT_STALE:
            ok = (
                local_new == wx_new
                and wx_new is not CONFLICT
                and old != wx_new
                and old != q6(ref_max.value)
                and old != q6(ref_min.value)
            )
        else:
            ok = False
        if not ok:
            failures.append(f"{code} {category} old={old} new={local_new}")
    assert not failures, failures[:FAILURE_LIST_LIMIT]
