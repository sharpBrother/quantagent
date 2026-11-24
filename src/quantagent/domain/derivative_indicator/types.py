"""衍生指标中的换手率行。数值保持源端精度，缺失保持为空。
字段依据：旧仓 ``factors/factors.py`` 的 ``MIF.col_lag`` 中的 ``S_DQ_TURN``。
该表行集含非交易日，读取方必须按行情的交易日取值，不能直接把本表当截面。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Turnover:
    trade_dt: date
    wind_code: str
    turnover: Decimal | None
