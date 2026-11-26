"""``pf_single_event_sue_1_mean_pos``：标准化未预期盈利 ``event_sue``。

复现旧仓 ``factors/factor_event_2.py`` 的 ``event_sue``（行号见 event-factors-handoff.md §3）。
口径（旧代码行为逐行复现；统计用 float，与旧代码 pandas float64 一致，不用 Decimal——
这里是浮点统计而非财务精度场景，用 Decimal 反而偏离旧行为）：

定义（旧 docstring）：

- ``NP_t`` 当期单季度归母净利润；
- ``E(NP_t)`` 当期预期单季净利润 = 去年同期单季净利 + 过去 8 期单季净利同比变化的均值；
- ``σ`` = 过去 8 期单季净利同比变化的标准差；
- ``sue = (NP_t − E(NP_t)) / σ``。

历史利润序列（``fin_income_gen``，``report_type in (1001,1003)`` 合并口径含调整）：

- 取 ``report_year >= 当期 − 4``、``report_year*10000+report_quarter < 当期``、
  ``declare_date <= 当期公告日`` 的行，按 ``report_year, report_quarter, report_type`` 升序。
  **不足 13 行直接放弃**（旧代码 ``if len(profit_data) < 13: return``）——13 行的来源：
  8 期同比 + 当期 + 去年同期至少要 4+8+1 行的序列长度才够，13 是经验下限。
- ``np_shareholder`` ÷10000 转万元后，**追加当期行**（report_year/report_quarter/profit）。
- ``period = report_year*10000 + report_quarter``，按 period 去重 ``keep='last'``。
  由于排序是 report_type 升序（1001 前 1003 后），同 period 保留 1003 调整版。
- **单季净利** ``np_shareholder_q = np_shareholder.diff()``（累计转单季），但 Q1
  （report_quarter==1001）直接用累计值（Q1 累计即单季）。
- **同比变化** ``q_diff_4 = np_shareholder_q.diff(periods=4)``（4 期前同季差分）。

统计窗口（两处窗口**不同**，旧代码如此，不可统一）：

- 预期均值：``period_ly = (report_year−1)*10000 + report_quarter``（去年同期）。若 period_ly
  在序列中，``exp_profit_q = profit_q_ly + q_diff_4.loc[:period_ly].tail(8).mean()``，
  其中 ``profit_q_ly`` 是 period_ly 处的单季净利。
- 标准差：``std_profit_q = q_diff_4.iloc[:-1].tail(8).std(ddof=1)``——``iloc[:-1]`` 去掉
  最后一行（当期行）再取 tail(8)。注意这里**不**按 period_ly 切片，而是全序列去掉当期。
- ``sue = (np_shareholder_q[-1] − exp_profit_q) / std_profit_q``。``np_shareholder_q[-1]``
  是追加的当期行的单季净利。NaN/inf 不产值（旧代码在外层 ``pd.notna`` 判断）。

缺失即缺失：``np_shareholder`` 为空的行在 diff/mean/std 中按 pandas 行为传播 NaN，
NaN 参与的统计量为 NaN，最终 sue 为 NaN 则不产值。不补 0、不插值。

方向 +1：未预期盈利为正是利好，越高越好。长表存原值，不乘符号。
"""

from __future__ import annotations

import math
import statistics
from typing import TYPE_CHECKING

from quantagent.platform.identity import digest_json

if TYPE_CHECKING:
    from collections.abc import Sequence

    from quantagent.domain.fundamental.types import ProfitSeriesRecord

FEATURE_ID = "pf_single_event_sue_1_mean_pos"
DEFINITION_VERSION = "v1"
# 过去 8 期单季净利同比变化进入预期均值与标准差。旧代码 tail(8)。
TAIL_PERIODS = 8
# 历史序列不足此行数直接放弃。旧代码 len(profit_data) < 13。
MIN_HISTORY_ROWS = 13
# 历史利润序列回退年数。旧代码 report_year >= 当期 − 4。
LOOKBACK_YEARS = 4
# 方向 +1：未预期盈利越高越好。
SIGN = 1
MEAN_WINDOW = 1

PARAMS = {
    "tail_periods": TAIL_PERIODS,
    "min_history_rows": MIN_HISTORY_ROWS,
    "lookback_years": LOOKBACK_YEARS,
    "sign": str(SIGN),
    "mean_window": MEAN_WINDOW,
}
PARAM_HASH = digest_json(PARAMS)


# 报告季度代码：一季报。Q1 单季净利直接用累计值（累计即单季），其余季度需 diff。
_Q1 = 1001
# 同比差分的期数跨度：4 个季度前即去年同季。
_YOY_LAG = 4
# 万元换算因子：fin_income_gen.np_shareholder 单位元，÷10000 转万。
_YUAN_TO_WAN = 10000.0
# 样本标准差（ddof=1）至少需要的非 NaN 观测数，不足则 pandas 得 NaN。
_MIN_STD_OBS = 2


def event_sue(
    *,
    report_year: int,
    report_quarter: int,
    profit: float,
    history: Sequence[ProfitSeriesRecord],
) -> float | None:
    """单个事件的 ``event_sue``。无法产值时返回 ``None``。

    ``profit`` 是当期归母净利润（万元，端口已统一换算）。``report_year``/``report_quarter``
    是当期报告期（quarter 为 1001-1004）。``history`` 是该股 ``report_type in (1001,1003)``、
    已按 ``declare_date <= 公告日`` 截止、``report_year >= report_year − 4`` 且早于当期的历史行，
    顺序任意（本函数内部按 report_year/report_quarter/report_type 排序复现旧 SQL ORDER BY）。

    返回 None 的情形：历史不足 13 行、去年同期不在序列、关键统计量为 NaN/inf、std 为 0 致除零。
    """
    rows = sorted(
        history,
        key=lambda r: (r.report_year, r.report_quarter, r.report_type),
    )
    if len(rows) < MIN_HISTORY_ROWS:
        return None

    dedup = _build_profit_series(rows, report_year, report_quarter, profit)
    np_q = _quarterly_net_profit(dedup)
    q_diff_4 = _yoy_diff(np_q)
    return _sue_from_series(dedup, np_q, q_diff_4, report_year, report_quarter)


def _build_profit_series(
    rows: Sequence[ProfitSeriesRecord],
    report_year: int,
    report_quarter: int,
    profit: float,
) -> list[tuple[int, int, float]]:
    """构造去重后的 ``(period, report_quarter, 累计净利万元)`` 序列，末尾追加当期行。

    按 period 去重 ``keep='last'``：同 period 保留序列中靠后的行。由于历史已按 report_type
    升序，同 period 的 1003 调整版在 1001 之后，keep='last' 保留 1003。dict 保序去重：
    ``order`` 记首现顺序（pandas 去重后行位置按首现），``last_value`` 取末次值（keep='last'）。
    """
    last_value: dict[int, tuple[int, float]] = {}
    order: list[int] = []

    def _append(period: int, qr: int, np_val: float) -> None:
        if period not in last_value:
            order.append(period)
        last_value[period] = (qr, np_val)

    for row in rows:
        np_val = (
            float(row.np_shareholder) / _YUAN_TO_WAN if row.np_shareholder is not None else math.nan
        )
        _append(row.report_year * 10000 + row.report_quarter, row.report_quarter, np_val)
    # 追加当期行（profit 已是万元）。历史 SQL 有 period < 当期，period 最大不冲突，在末尾。
    _append(report_year * 10000 + report_quarter, report_quarter, profit)
    return [(p, last_value[p][0], last_value[p][1]) for p in order]


def _quarterly_net_profit(dedup: Sequence[tuple[int, int, float]]) -> list[float]:
    """累计转单季：``diff()``，但 Q1 直接用累计值。逐行复现 pandas.Series.diff。

    非 Q1 的第一行没有前一行可减，得 NaN（pandas diff 首行 NaN）。
    """
    np_cum = [item[2] for item in dedup]
    qrs = [item[1] for item in dedup]
    np_q: list[float] = []
    for i, val in enumerate(np_cum):
        if qrs[i] == _Q1:
            np_q.append(val)
        elif i == 0:
            np_q.append(math.nan)
        else:
            np_q.append(val - np_cum[i - 1])
    return np_q


def _yoy_diff(np_q: Sequence[float]) -> list[float]:
    """单季净利的 4 期差分（同比变化）。前 4 行 NaN。"""
    q_diff_4: list[float] = []
    for i, val in enumerate(np_q):
        if i < _YOY_LAG:
            q_diff_4.append(math.nan)
        else:
            q_diff_4.append(val - np_q[i - _YOY_LAG])
    return q_diff_4


def _sue_from_series(
    dedup: Sequence[tuple[int, int, float]],
    np_q: Sequence[float],
    q_diff_4: Sequence[float],
    report_year: int,
    report_quarter: int,
) -> float | None:
    """由单季净利与同比序列算 sue。两处统计窗口不同（见模块 docstring），不可合并。"""
    period_ly = (report_year - 1) * 10000 + report_quarter
    periods = [item[0] for item in dedup]
    if period_ly not in periods:
        return None

    ly_idx = periods.index(period_ly)
    profit_q_ly = np_q[ly_idx]

    # 预期均值窗口：q_diff_4 截至 period_ly（含）的 tail(8)，跳过 NaN 取均值。
    window_mean_vals = _tail_non_nan(q_diff_4[: ly_idx + 1])
    if not window_mean_vals:
        return None
    exp_profit_q = profit_q_ly + statistics.mean(window_mean_vals)

    # 标准差窗口：q_diff_4 去掉最后一行（当期行）的 tail(8)，ddof=1。iloc[:-1] 去当期。
    window_std_vals = _tail_non_nan(q_diff_4[:-1])
    if len(window_std_vals) < _MIN_STD_OBS:
        # ddof=1 至少需 2 个非 NaN 值；否则 pandas 得 NaN，不产值。
        return None
    std_profit_q = statistics.stdev(window_std_vals)

    cur_np_q = np_q[-1]
    # 除零产生 inf、NaN 传播都导致 sue 不可用，旧代码外层 pd.notna/isinf 一并剔除。统一在此不产值。
    if (
        math.isnan(cur_np_q)
        or math.isnan(exp_profit_q)
        or math.isnan(std_profit_q)
        or std_profit_q == 0.0
    ):
        return None
    sue = (cur_np_q - exp_profit_q) / std_profit_q
    if math.isnan(sue) or math.isinf(sue):
        return None
    return sue


def _tail_non_nan(values: Sequence[float]) -> list[float]:
    """取序列末尾 ``TAIL_PERIODS`` 个中的非 NaN 值（pandas tail(8) 后 mean/std 跳过 NaN）。"""
    return [v for v in values[-TAIL_PERIODS:] if not math.isnan(v)]
