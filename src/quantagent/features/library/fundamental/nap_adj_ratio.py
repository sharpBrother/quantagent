"""``pf_single_nap_adj_ratio_1_mean_pos``：朝阳永续盈利预测上调幅度中位数 ``nap_adj_ratio``。

复现旧仓 ``factors/factor_rpt.py`` 的 ``NAP_ADJ_RATIO.process`` 与 ``DailyFactorEarnAdj`` 取数逻辑，
行号见 ``docs/adr/<nap_adj_ratio ADR>``。口径（旧代码行为；偏离处标注）：

- 观察日 ``day``。业务窗口为 ``current_create_date ∈ [day − 30 天, day]``，含两端（旧代码
  ``date_0 <= current_create_date <= date``，``date_0 = day − timedelta(days=30)``）。
- 可见性：负责人 2026-11-26 裁定，可见截止用入库时间 ``entrytime ≤ day``，**不按**研报日期
  ``current_create_date`` 截止。旧仓只按 ``current_create_date`` 过滤，会提前看到尚未入库的调整
  （前视，见 ``docs/adr/2026-11-24-suntime-visibility.md``）；本实现加 entrytime 截止消除前视，
  因此与 wx2 旧值不逐行一致，golden 用 wx2 源输入经同一函数重算比对。这是有意的口径改进，
  不是缺陷。窗口仍按 ``current_create_date``（业务语义不变），entrytime 只管"能不能看到"。
- 窗口内该行 ``entrytime`` 必须不晚于 ``day`` 才纳入计算（当日已入库可见）。读取端口已按
  ``as_of`` 截止 entrytime，进入本函数的行都满足 ``entrytime ≤ as_of``；截面日 ``day ≤ as_of``
  时历史行仍可能 ``entrytime`` 晚于 ``day``，须在本函数内再过滤——这是与 did_ratio 的关键差别
  （did_ratio 的 ANN_DT 既是窗口列又是可见列，本因子两者分离）。
- 窗口内无有效行时不产值（旧代码 ``if not rpt_data.empty``，空则返回 ``None``）。
- 计算：窗口行按 ``report_year`` 分组数 ``organ_id`` 条数，取条数最多的年度；该年度的
  ``np_adjust_rate`` 取中位数（``quantile(0.5)``，偶数个取中间两值线性插值即均值）。
- 并列年度：``adj_num.sort_values(ascending=False).index[0]``。groupby 的 index 按 report_year
  升序，计数并列时取并列中的第一个。用 ``legacy_descending_order`` 逐行复现旧仓 quicksort
  并列顺序（见 ``docs/adr/2026-11-22-cutamp-legacy-quicksort-order.md``）。窗口内年度很少，
  但不假设规模，按 ``_legacy_sort`` 原则复现。
- ``np_adjust_rate`` 为空的行：旧代码 ``quantile`` 会自动跳过 NaN（pandas 默认）。本实现
  同样只取非空值参与中位数；若该年度全部为空，中位数为空，不产值。
- 旧代码数据源 ``stock_code not like '2%'`` 剔除深 B。新仓按 all_a 减 ST 取域（见 panel），
  B 股/基金代码本就不在 all_a 域内，由域过滤天然剔除，不在本函数重复。

方向 +1：上调盈利预测（np_adjust_rate 为正）是利好，越高越好。长表存原值，不乘符号。
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from quantagent.features.library._legacy_sort import legacy_descending_order
from quantagent.platform.identity import digest_json

if TYPE_CHECKING:
    from collections.abc import Sequence

    from quantagent.domain.fundamental.types import EarningsAdjustRecord

FEATURE_ID = "pf_single_nap_adj_ratio_1_mean_pos"
DEFINITION_VERSION = "v1"
# 业务窗口 30 个自然日，含观察日当天。旧代码 ``timedelta(days=30)``。
WINDOW_DAYS = 30
# 方向 +1：上调幅度越高越好。
SIGN = 1
MEAN_WINDOW = 1

PARAMS = {
    "window_days": WINDOW_DAYS,
    "sign": str(SIGN),
    "mean_window": MEAN_WINDOW,
}
PARAM_HASH = digest_json(PARAMS)


def adjust_window_rows(
    *,
    as_of: date,
    rows: Sequence[EarningsAdjustRecord],
) -> tuple[EarningsAdjustRecord, ...]:
    """裁剪到观察日 ``as_of`` 可见且在业务窗口内的行。库函数与面板共用，保证血缘取实际输入。

    两步裁剪：

    1. 可见性：``entrytime ≤ as_of``（截面日历史行的 entrytime 可能晚于观察日，须剔除）。
    2. 业务窗口：``current_create_date ∈ [as_of − 30 天, as_of]``。
    """
    lower = as_of - timedelta(days=WINDOW_DAYS)
    return tuple(
        row for row in rows if row.entry_dt <= as_of and lower <= row.create_dt <= as_of
    )


def nap_adj_ratio(
    *,
    as_of: date,
    rows: Sequence[EarningsAdjustRecord],
) -> Decimal | None:
    """单只股票在观察日 ``as_of`` 的 ``nap_adj_ratio``。无法产值时返回 ``None``。

    ``rows`` 是读取端口按 ``as_of`` 截止 entrytime 后、该股 ``current_create_date`` 落在
    更宽读取区间内的全部行。本函数用 ``adjust_window_rows`` 裁剪出实际进入计算的窗口行。
    """
    window = adjust_window_rows(as_of=as_of, rows=rows)
    if not window:
        return None

    # 按 report_year 分组数 organ_id 条数。groupby 的 index 按年度升序。
    count_by_year: dict[int, int] = {}
    for row in window:
        if row.report_year is None:
            # 旧代码 groupby 会把 report_year 为 NaN 的行排除在分组外（pandas 默认 dropna）。
            continue
        count_by_year[row.report_year] = count_by_year.get(row.report_year, 0) + 1
    if not count_by_year:
        return None

    years_sorted = sorted(count_by_year)  # groupby index 升序
    counts = [float(count_by_year[year]) for year in years_sorted]
    # 复现旧仓 sort_values(ascending=False).index[0]：计数并列时取并列中第一个（升序 index 下较小年度）。
    order = legacy_descending_order(counts)
    adj_year = years_sorted[order[0]]

    rates = [
        row.np_adjust_rate
        for row in window
        if row.report_year == adj_year and row.np_adjust_rate is not None
    ]
    if not rates:
        return None
    return _median(rates)


def _median(values: list[Decimal]) -> Decimal:
    """pandas ``quantile(0.5)``：奇数取中位，偶数取中间两值的均值（线性插值）。"""
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / Decimal(2)
