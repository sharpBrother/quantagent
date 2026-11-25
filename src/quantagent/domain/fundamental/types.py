"""分红、利润表与财务指标的窄读取行，只含 did_ratio 需要的字段。

``ann_dt`` 是源端 ``ANN_DT``，即可见日；读取端口已按 as_of 截止，``ann_dt`` 不会晚于 as_of。
``report_period`` 是 ``REPORT_PERIOD`` 解析出的报告期末日。同一 (代码, 报告期) 的修订去重
不在端口做，由使用方按口径决定，见 ``features.library.fundamental.did_ratio``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal


@dataclass(frozen=True, slots=True)
class DividendRecord:
    asset_id: str
    ann_dt: date
    report_period: date
    # 单位与源端 TOT_CASH_DVD 一致（元）。空值保留为 None，由使用方决定如何处理。
    tot_cash_dvd: Decimal | None


@dataclass(frozen=True, slots=True)
class NetProfitRecord:
    asset_id: str
    ann_dt: date
    report_period: date
    # 扣除非经常性损益后归属于母公司股东的净利润，源端 NET_PROFIT_AFTER_DED_NR_LP。
    net_profit_after_ded: Decimal | None


@dataclass(frozen=True, slots=True)
class IndicatorRecord:
    """财务指标行。只用于判断窗口内是否有季末报告期的行，不带指标值。"""

    asset_id: str
    ann_dt: date
    report_period: date
