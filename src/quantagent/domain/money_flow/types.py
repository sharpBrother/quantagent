"""资金流行。字段只含 Current-20 第二批三个资金流因子实际读取的列，数值保持源端精度，缺失保持为空。

字段依据（旧仓读取 SQL 与因子 ``col_lag``）：
- ``pf_single_abso_umr``：``BUY_VALUE_SMALL_ORDER_ACT``（``guosen_umr.py`` 的 ``ABSO``）
- ``pf_single_moneyflowh``：``VALUE_DIFF_*`` 四个量差（``factors/factors.py`` 的 ``MONEYFLOWH``）
- ``pf_single_actlargemedcut``：大单与中单的主动买卖金额四列（``factors/factors.py`` 的 ``ACTLARGEMEDCUT``）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal


@dataclass(frozen=True, slots=True)
class MoneyFlow:
    trade_dt: date
    wind_code: str
    buy_value_small_order_act: Decimal | None
    buy_value_med_order_act: Decimal | None
    buy_value_large_order_act: Decimal | None
    sell_value_med_order_act: Decimal | None
    sell_value_large_order_act: Decimal | None
    value_diff_small_trader: Decimal | None
    value_diff_med_trader: Decimal | None
    value_diff_large_trader: Decimal | None
    value_diff_institute: Decimal | None
