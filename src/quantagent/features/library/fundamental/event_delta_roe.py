"""``pf_single_event_delta_roe_1_mean_pos``：盈余公告 ROE 同比变化 ``event_delta_roe``。

复现旧仓 ``factors/factor_event_2.py`` 的 ``event_delta_roe``（行号见 event-factors-handoff.md §4）。

定义：``delta_roe = 当期 ROE − 去年同期 ROE``。``confirm_date = declare_date``（不依赖行情，
``event_dt = declare_date``，与 event_sue 同——区别于 event_aog 的 open_date）。

算法（旧代码逐行复现）：

1. ``roe_last``（去年同期 ROE）：``ASHAREFINANCIALINDICATOR.S_QFA_ROE``，``REPORT_PERIOD = period_ly``、
   ``ANN_DT <= declare_date``，按 ANN_DT 排序取**最后一行**（``iloc[-1]``，多次公告取最新）。
   **``period_ly`` 不在结果中则整个事件不产值**（外层硬条件）。
2. 当期 ``roe``：
   - ``period`` 在结果中且 ``S_QFA_ROE`` 非空 → 用 Wind 值（多数情况）。
   - 否则用 profit 重算 ``roe = 100 * profit_q / eqt``：
     - ``profit`` 按来源分支（np_floor/np/np_shareholder÷10000，端口已统一为万元）。
     - ``eqt`` = ``get_shrhldr_eqt(上一期)`` 股东权益 ÷10000（转万）。**上一期**用 ``get_last_period``。
     - ``profit_q`` 单季利润：Q1（mmdd=0331）直接用 profit（累计即单季）；否则
       ``profit − get_profit(上一期)``。
3. ``delta_roe = roe − roe_last``，两者皆非空非 NaN 才产出。

辅助（``factor_event_2.py:639-700``）：

- ``get_last_period(period)``：上一报告期。0331→前年1231；0630→0331；0930→0630；1231→0930。
- ``get_profit(period)``：``fin_income_gen`` 该期归母净利润 ÷10000。``report_type desc`` 取首行
  （1003 调整版优先于 1001）。panel 从利润序列行复现。
- **股东权益不按 ann_dt 截止**（旧代码 ``get_shrhldr_eqt`` 只按 report_period 取，不看公告日）——
  潜在前视，复现旧行为，golden 登记。批量读取的 as_of 截止是唯一的 ann_dt 过滤。

方向 +1：ROE 提升是利好，越高越好。长表存原值，不乘符号。
"""

from __future__ import annotations

import math

from quantagent.platform.identity import digest_json

FEATURE_ID = "pf_single_event_delta_roe_1_mean_pos"
DEFINITION_VERSION = "v1"
# 方向 +1：ROE 同比提升越高越好。
SIGN = 1
MEAN_WINDOW = 1

PARAMS = {
    "sign": str(SIGN),
    "mean_window": MEAN_WINDOW,
}
PARAM_HASH = digest_json(PARAMS)

# 万元换算：fin_income_gen.np_shareholder 与股东权益单位都是元，÷10000 转万（旧代码一致）。
_YUAN_TO_WAN = 10000.0
# 报告期 mmdd 标记：Q1 期末 0331。Q1 单季利润直接用累计值。
_Q1_MMDD = (3, 31)
# 季度 mmdd 序列（0331/0630/0930/1231），get_last_period 索引用。
_MMDD_LIST = ((3, 31), (6, 30), (9, 30), (12, 31))


def last_period(year: int, quarter: int) -> tuple[int, int]:
    """上一报告期 ``(report_year, report_quarter)``。复现旧 ``get_last_period``。

    quarter 为 1001-1004。0331(1001)→前一年 1004；其余→同年前一季度。
    """
    idx = {1001: 0, 1002: 1, 1003: 2, 1004: 3}[quarter]
    if idx == 0:
        return (year - 1, 1004)
    prev_quarter = {1: 1001, 2: 1002, 3: 1003}[idx]
    return (year, prev_quarter)


def event_delta_roe(
    *,
    roe_current: float | None,
    roe_last: float | None,
) -> float | None:
    """``delta_roe = roe_current − roe_last``。任一缺失/NaN 返回 None。

    本函数只做最终差值。``roe_current`` 的 Wind 优先/profit 重算二分支与 ``roe_last`` 的
    取数在 panel（需访问序列）。这是纯函数出口，对应旧代码末尾 ``roe - roe_last``。
    """
    if roe_current is None or roe_last is None:
        return None
    if math.isnan(roe_current) or math.isnan(roe_last):
        return None
    return roe_current - roe_last


def recomputed_roe(*, profit_q: float | None, equity_wan: float | None) -> float | None:
    """重算 ROE ``100 * profit_q / eqt``。eqt 为 0/缺失或 profit_q 缺失返回 None（不除零）。

    ``profit_q`` 与 ``equity_wan`` 都是万元。对应旧代码 profit 重算分支（Wind ROE 缺失时）。
    """
    if profit_q is None or equity_wan is None:
        return None
    if math.isnan(profit_q) or math.isnan(equity_wan):
        return None
    if equity_wan == 0:
        return None
    return 100.0 * profit_q / equity_wan
