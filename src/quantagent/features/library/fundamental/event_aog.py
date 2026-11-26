"""``pf_single_event_aog_1_mean_pos``：盈余公告开盘跳空 ``event_aog``。

复现旧仓 ``factors/factor_event_2.py`` 的 ``event_aog``（行号见 event-factors-handoff.md §4）。

定义（旧 docstring）：个股盈余公告次日开盘价/昨日收盘价 − 中证 500 指数次日开盘价/昨日收盘价。

- ``个股 night_ratio`` = ``100*(S_DQ_ADJOPEN/S_DQ_ADJPRECLOSE - 1)``（复权开盘/复权前收，从
  ``ASHAREEODPRICES`` 重算——已实证与旧仓 ``stock_ratio.night_ratio`` 完全一致，差异 < 5e-5
  是 wx2 存储舍入）。复权口径避免分红除权造成的假跳空。
- ``指数 night_ratio`` = ``100*(S_DQ_OPEN/S_DQ_PRECLOSE - 1)``（中证 500 ``000905.SH``，
  指数不复权）。aog = 个股 night_ratio − 指数 night_ratio，剔除市场开盘整体高开的部分。

开盘日判定（``open_date``，负责人 2026-11-26 裁定沿用旧仓）：

- ``entrytime < declare_date``（前一晚已入库），**或** 同日 ``entrytime`` 时分 ``%H%M <= '0925'``
  （集合竞价 9:25 结束前入库）→ 公告**当日**首个交易日开盘反映；
- 其他 → 公告**次日**首个交易日开盘反映。

``entrytime`` 在此的角色是市场微观结构建模（开盘价何时消化财报），**不是** PIT 可见性字段
（可见性截止仍是 ``declare_date``）——两者职责不同，见 ADR。

PIT 语义（下游 ``alpha_factory/etf/gateway.py`` 注释：``event_*`` 的 effective date 是
``confirm_date``）：``confirm_date = open_date``，``event_dt = open_date``。因子值描述的是
open_date 的开盘跳空，且依赖 open_date 行情才知道——``event_dt`` 取 open_date 而非 declare_date，
``knowledge_dt`` 箍到 open_date。若用 declare_date 会在开盘前前视未知的开盘涨幅。

方向 +1：跳空高开是利好，越高越好。长表存原值，不乘符号。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.platform.identity import digest_json

if TYPE_CHECKING:
    from datetime import date, datetime

FEATURE_ID = "pf_single_event_aog_1_mean_pos"
DEFINITION_VERSION = "v1"
# 方向 +1：跳空高开越大越好。
SIGN = 1
MEAN_WINDOW = 1
# 集合竞价结束时刻。entrytime 同日且 %H%M <= 此值则公告当日开盘反映。旧代码 '0925'。
CALL_AUCTION_END_HHMM = "0925"
# 基准指数：中证 500。旧代码 S_INFO_WINDCODE = '000905.SH'。
BENCHMARK_INDEX = "000905.SH"

PARAMS = {
    "sign": str(SIGN),
    "mean_window": MEAN_WINDOW,
    "call_auction_end": CALL_AUCTION_END_HHMM,
    "benchmark_index": BENCHMARK_INDEX,
}
PARAM_HASH = digest_json(PARAMS)

# 时分钟点格式长度（%H%M），'0925'。
_HHMM_LEN = 4


def event_aog(
    *,
    stock_night_ratio: float,
    index_night_ratio: float,
) -> float:
    """单个事件的 ``event_aog`` = 个股夜盘涨幅 − 指数夜盘涨幅。

    纯差值计算，口径难点在 open_date 判定与 night_ratio 重算（分别在 ``reflect_open_date``
    与 panel）。两个 night_ratio 都非空才调用本函数（panel 保证），返回值恒有限。
    """
    return stock_night_ratio - index_night_ratio


def night_ratio(open_price: float, preclose: float) -> float | None:
    """``100*(open/preclose - 1)``。preclose 为 0 或负（异常）返回 None，不除零。"""
    if preclose <= 0:
        return None
    return 100.0 * (open_price / preclose - 1.0)


def reflect_same_day(entrytime: datetime | None, declare_dt: date) -> bool:
    """事件结果是否在公告**当日**首个交易日开盘反映。

    复现旧仓 ``factor_event_2.py`` 的两条件取或（``entrytime`` 带时分秒；``declare_dt`` 是公告日，
    源端 datetime 恒为 00:00，此处取 date 语义）：

    - ``entrytime`` 日期部分早于公告日（前一晚已入库——财报实际前一晚进库，次日才正式“宣告”）
      → 当日反映；
    - 或 ``entrytime`` 与公告同日且时分 ``%H%M <= '0925'``（集合竞价结束前入库）→ 当日反映。

    其他 → 次日首个交易日。``entrytime`` 缺失返回 False（保守取次日，不猜测）。本函数只判定
    当日/次日；open_date 落在哪个交易日由 panel 用交易日历解析（declare 当日若非交易日取其后首个）。
    """
    if entrytime is None:
        return False
    if entrytime.date() < declare_dt:
        return True
    return entrytime.date() == declare_dt and entrytime.strftime("%H%M") <= CALL_AUCTION_END_HHMM
