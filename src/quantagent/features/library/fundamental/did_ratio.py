"""``pf_single_stock_did_ratio_did_ratio_realized_1_1_mean_pos``：稳健股息率 ``did_ratio_realized_1``。

复现旧仓 ``factors/factor_fundamental.py`` 的 ``DIVIDEND.get_stock_did`` 中 ``did_ratio_realized_1`` 一支，
行号见 ``docs/adr/2026-11-25-did-ratio.md``。``payout_his``、``payout_ratio_2``、``did_ratio_2``、
``did_ratio_realized_2``、``roe_score`` 不属于本因子，不复现。

口径（旧代码行为；偏离处标注）：

- 观察日 ``as_of`` 是交易日 T。窗口为 ``ANN_DT ∈ (T − 1825 天, T]``，与旧 SQL 的
  ``ANN_DT > data_start_date`` 及 ``ANN_DT <= date`` 一致。旧代码用 ``timedelta(days=5*365)``，不是 5 个日历年。
- 只取季末报告期（末四位 0331/0630/0930/1231）。
- 同一 (代码, 报告期) 有多条修订时取 ANN_DT 最大的一条。旧代码 ``drop_duplicates(keep="last")`` 作用在
  ``ORDER BY REPORT_PERIOD`` 的结果上，同报告期内的顺序没有保证，本实现不复现该顺序。
  同一最大 ANN_DT 下出现不同取值时 fail-closed，不猜测取哪一条。
- 利润表只取 ``STATEMENT_TYPE = 408001000``（由端口过滤）。
- 窗口内没有季末财务指标行，或没有季末利润表行，该股不产值（旧代码 ``continue``）。
- 市值缺失不产值。
- 分红先按报告期去重，再剔除 ``TOT_CASH_DVD`` 为空的报告期（旧代码 ``dropna`` 在去重之后）。
- 负责人裁定 A（2026-11-25）：没有分红记录，因子为 0。旧代码在分红为空时直接给 0。
  包括窗口内有分红但报告期全部早于 3 年截止的情形，旧代码同样走 ``dividend.empty`` 分支。
- 负责人裁定 B：最新 TTM 扣非净利润 ≤ 0，``did_ratio_1 = 0``，因子为 0。
- 负责人裁定 C：近 3 年没有盈利年份，``payout_ratio_1`` 为空，``did_ratio_1 = 0``，因子为 0。
  旧代码 ``min(80, NaN)`` 在 Python 中返回 80，使派息率变成 80%，这是旧代码的缺陷。
- 最新 TTM 缺失（相邻季度缺行，单季无法差分）时不产值。旧代码在此退回 ``did_ratio_realized`` 且不封顶，
  属于缺输入时的回退，不复现（调度方裁定 2，见 ADR）。窗口内没有分红记录时仍按裁定 A 输出 0，不受此影响。
- 派息率封顶 80%（``min(80, payout_ratio_1)``）保留。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Context, Decimal, localcontext
from typing import TYPE_CHECKING

from quantagent.domain.errors import FeatureLookupError
from quantagent.domain.fundamental.types import DividendRecord, IndicatorRecord, NetProfitRecord
from quantagent.platform.identity import digest_json

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

FEATURE_ID = "pf_single_stock_did_ratio_did_ratio_realized_1_1_mean_pos"
DEFINITION_VERSION = "v1"
# 旧代码 ``timedelta(days=5 * 365)``。是 1825 个日历日，不是 5 个日历年。
WINDOW_DAYS = 5 * 365
# 利润表的报表类型。只取合并报表，与旧代码的 ``STATEMENT_TYPE = 408001000`` 一致。
STATEMENT_TYPE = "408001000"
# 派息率封顶，旧代码 ``min(80, payout_ratio_1)``。
PAYOUT_CAP = Decimal(80)
# 方向 +1：稳健股息率越高越好。长表存原值，不乘符号。
SIGN = 1
# Current-20 消费窗口 1，取截面日当天的值。
MEAN_WINDOW = 1
DIVIDEND_YEARS = 3
# 一季报、年报、TTM 所需的单季数。
_Q1_MONTH = 3
_ANNUAL_MONTH = 12
_TTM_QUARTERS = 4

PARAMS = {
    "window_days": WINDOW_DAYS,
    "statement_type": STATEMENT_TYPE,
    "payout_cap_pct": str(PAYOUT_CAP),
    "dividend_years": DIVIDEND_YEARS,
    "sign": str(SIGN),
    "mean_window": MEAN_WINDOW,
}
PARAM_HASH = digest_json(PARAMS)


class DidRatioConflictError(FeatureLookupError):
    """同一 (代码, 报告期) 在最大公告日有两个不同取值，无法判定取哪一个。调用方应只跳过该股该日，不改口径。"""


_QUARTER_ENDS = frozenset({(3, 31), (6, 30), (9, 30), (12, 31)})
# 60 位有效数字足以覆盖除法链。与旧代码 float64 的差异远小于 numeric(10,6) 的量化步长。
_CONTEXT = Context(prec=60)

# 三类输入行共用的上界。去重与季末过滤只依赖 report_period、ann_dt、asset_id 这三个字段。
_Record = DividendRecord | NetProfitRecord | IndicatorRecord


@dataclass(frozen=True, slots=True)
class DidWindowRows:
    """窗口内、季末报告期的输入行。它们是本因子实际读取的输入，也是血缘推导的依据。"""

    dividends: tuple[DividendRecord, ...]
    net_profits: tuple[NetProfitRecord, ...]
    indicators: tuple[IndicatorRecord, ...]


@dataclass(frozen=True, slots=True)
class _Point:
    """一个报告期的取值。利润表的 ``value`` 为扣非净利润，允许为空。"""

    report: date
    value: Decimal | None


def window_rows(
    *,
    as_of: date,
    dividends: Sequence[DividendRecord],
    net_profits: Sequence[NetProfitRecord],
    indicators: Sequence[IndicatorRecord],
) -> DidWindowRows:
    """裁剪到 ``ANN_DT ∈ (as_of − 1825 天, as_of]`` 且季末报告期的行。单只股票的输入。"""
    lower = as_of - timedelta(days=WINDOW_DAYS)

    def keep[Row: _Record](rows: Sequence[Row]) -> tuple[Row, ...]:
        return tuple(
            row
            for row in rows
            if lower < row.ann_dt <= as_of and _is_quarter_end(row.report_period)
        )

    win = DidWindowRows(
        dividends=keep(dividends),
        net_profits=keep(net_profits),
        indicators=keep(indicators),
    )
    codes = {
        row.asset_id for group in (win.dividends, win.net_profits, win.indicators) for row in group
    }
    if len(codes) > 1:
        raise FeatureLookupError(f"did_ratio 输入混入多只股票: {sorted(codes)}")
    return win


def did_ratio_realized_1(
    *,
    as_of: date,
    dividends: Sequence[DividendRecord],
    net_profits: Sequence[NetProfitRecord],
    indicators: Sequence[IndicatorRecord],
    market_value: Decimal | None,
) -> Decimal | None:
    """单只股票在观察日 ``as_of`` 的 ``did_ratio_realized_1``。无法产值时返回 ``None``。

    ``market_value`` 是 T 当日 ``S_VAL_MV``，单位万元。``None`` 表示没有市值。
    """
    win = window_rows(
        as_of=as_of,
        dividends=dividends,
        net_profits=net_profits,
        indicators=indicators,
    )
    # 旧代码：ROE 或利润表为空直接跳过。ROE 只判断是否存在，不参与本因子的计算。
    if not win.indicators or not win.net_profits:
        return None
    if market_value is None:
        return None
    if market_value <= 0:
        raise FeatureLookupError(f"S_VAL_MV 非正，拒绝计算: {market_value}")

    dvd_points = _dividend_points(win.dividends)
    if not dvd_points:
        # 裁定 A：窗口内没有分红记录，因子为 0。
        return Decimal(0)

    with localcontext(_CONTEXT):
        mv_yuan = market_value * Decimal(10000)
        profits = _profit_points(win.net_profits)
        ttm = _ttm_at_latest(profits)

        # 旧代码：lst = max(最新分红报告期, 前年 1231)。
        latest_report = max(point.report for point in dvd_points)
        lst = max(latest_report, date(as_of.year - 2, 12, 31))
        # 旧代码：只保留报告期不早于 (lst 年 − 2) 年 1 月 1 日的分红与利润表。
        cutoff = date(lst.year - DIVIDEND_YEARS + 1, 1, 1)
        divs = [point for point in dvd_points if point.report >= cutoff]
        if not divs:
            # 裁定 A 的另一种情形：分红全部早于 3 年截止，旧代码走 dividend.empty 分支。
            return Decimal(0)
        last_div = max(point.report for point in divs)
        incs = [point for point in profits if cutoff <= point.report <= last_div]

        num_months = 2 * 12 + lst.month
        total_dvd = sum((point.value or Decimal(0) for point in divs), Decimal(0))
        realized = Decimal(100) * total_dvd / mv_yuan / (Decimal(num_months) / Decimal(12))

        payout = _payout_pct(lst, divs, incs)

        if ttm is None:
            # 裁定 2：最新 TTM 为空（相邻季度缺行，单季无法差分）时不产值。
            # 旧代码在此退回 did_ratio_realized 且不封顶，属于缺输入时的回退，不复现。
            return None
        if ttm <= 0:
            # 裁定 B：最新 TTM 扣非净利润不为正，派息能力为 0。
            did_ratio_1 = Decimal(0)
        elif payout is None:
            # 裁定 C：近 3 年没有盈利年份。旧代码 min(80, NaN) = 80 是缺陷，修正为 0。
            did_ratio_1 = Decimal(0)
        else:
            did_ratio_1 = min(payout, PAYOUT_CAP) / (mv_yuan / ttm)
        return min(realized, did_ratio_1)


def _is_quarter_end(report: date) -> bool:
    return (report.month, report.day) in _QUARTER_ENDS


def _latest_per_report[Row: _Record](
    rows: Sequence[Row],
    *,
    value_of: Callable[[Row], Decimal | None],
    label: str,
) -> list[Row]:
    """每个报告期保留 ANN_DT 最大的一条。同一最大 ANN_DT 下取值不一致则拒绝，不猜测。"""
    by_report: dict[date, list[Row]] = {}
    for row in rows:
        by_report.setdefault(row.report_period, []).append(row)
    out: list[Row] = []
    for report in sorted(by_report):
        bucket = by_report[report]
        newest_ann = max(row.ann_dt for row in bucket)
        newest = [row for row in bucket if row.ann_dt == newest_ann]
        if len({value_of(row) for row in newest}) > 1:
            raise DidRatioConflictError(
                f"{label}同一报告期同一公告日取值不一致: "
                f"{newest[0].asset_id} {report.isoformat()} {newest_ann.isoformat()}"
            )
        out.append(newest[0])
    return out


def _dividend_points(rows: Sequence[DividendRecord]) -> list[_Point]:
    """去重后剔除 TOT_CASH_DVD 为空的报告期，按报告期升序。"""
    latest = _latest_per_report(rows, value_of=lambda row: row.tot_cash_dvd, label="分红")
    return [
        _Point(report=row.report_period, value=row.tot_cash_dvd)
        for row in latest
        if row.tot_cash_dvd is not None
    ]


def _profit_points(rows: Sequence[NetProfitRecord]) -> list[_Point]:
    latest = _latest_per_report(
        rows,
        value_of=lambda row: row.net_profit_after_ded,
        label="利润表",
    )
    return [_Point(report=row.report_period, value=row.net_profit_after_ded) for row in latest]


# 各季末的上一个季末（月, 日）。一季报的上一期是上年年报，与旧代码 ``get_last_period`` 一致。
_PREV_QUARTER_END: dict[int, tuple[int, int]] = {3: (12, 31), 6: (3, 31), 9: (6, 30), 12: (9, 30)}


def _prev_quarter_end(report: date) -> date:
    month, day = _PREV_QUARTER_END[report.month]
    year = report.year - 1 if report.month == _Q1_MONTH else report.year
    return date(year, month, day)


def _quarter_values(points: Sequence[_Point]) -> list[Decimal | None]:
    """单季值，复现 ``RAW._add_quarter_col``。

    一季报取累计值本身。其他季报取与上一条记录的差。上一条记录不是紧邻的上一季度末（中间缺报告期）时为空。
    旧代码的 ``is_last`` 检查正是这一条：``REPORT_PERIOD_LAST`` 必须等于上一季度末。
    """
    out: list[Decimal | None] = []
    for index, point in enumerate(points):
        if index == 0 or points[index - 1].report != _prev_quarter_end(point.report):
            out.append(None)
        elif point.report.month == _Q1_MONTH:
            out.append(point.value)
        else:
            prev = points[index - 1].value
            out.append(None if point.value is None or prev is None else point.value - prev)
    return out


def _ttm_at_latest(points: Sequence[_Point]) -> Decimal | None:
    """最新一条记录的 TTM 扣非净利润，复现 ``_add_quarter_col`` 之后的 ``profit_ttm``。

    年报行直接取年度值（旧代码 ``income.loc[is_fiscal, 'profit_ttm'] = raw``）。
    其他行取最近四个单季之和，任一为空则为空（``rolling(4).sum()`` 的 ``min_periods=4`` 行为）。
    """
    if not points:
        return None
    last = points[-1]
    if last.report.month == _ANNUAL_MONTH:
        return last.value
    quarters = _quarter_values(points)
    if len(quarters) < _TTM_QUARTERS:
        return None
    tail = quarters[-_TTM_QUARTERS:]
    if any(value is None for value in tail):
        return None
    return sum((value for value in tail if value is not None), Decimal(0))


def _payout_pct(
    lst: date,
    divs: Sequence[_Point],
    incs: Sequence[_Point],
) -> Decimal | None:
    """近 3 年盈利年份的累计派息率（百分比），复现 ``payout_ratio_1``，未封顶。无盈利年份返回 ``None``。

    分子取盈利年份的分红合计，分母取这些年份的利润表值。年份的利润表值取该年最新报告期的一条，
    与旧代码 ``groupby('year')['REPORT_PERIOD'].max()`` 一致。
    """
    years = [lst.year - 2, lst.year - 1, lst.year]
    year_did = {year: Decimal(0) for year in years}
    for point in divs:
        if point.report.year in year_did:
            year_did[point.report.year] += point.value or Decimal(0)
    # incs 按报告期升序，后写入的覆盖前面的，结果即该年最新报告期。
    year_income: dict[int, Decimal | None] = {}
    for point in incs:
        year_income[point.report.year] = point.value
    positive: list[int] = []
    for year in years:
        value = year_income.get(year)
        if value is not None and value > 0:
            positive.append(year)
    if not positive:
        return None
    did_sum = sum((year_did[year] for year in positive), Decimal(0))
    income_sum = sum((year_income[year] or Decimal(0) for year in positive), Decimal(0))
    return Decimal(100) * did_sum / income_sum
