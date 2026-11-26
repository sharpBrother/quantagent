"""指数日收益。涨跌幅保持源端精度，缺失保持为空。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal


@dataclass(frozen=True, slots=True)
class IndexReturn:
    trade_dt: date
    wind_code: str
    pct_change: Decimal | None
    # 开盘价与前收盘价（S_DQ_OPEN/S_DQ_PRECLOSE），event_aog 算指数夜盘涨幅
    # 100*(open/preclose-1) 所需。夜盘涨幅不能用 pct_change（收盘价涨跌）替代。
    open: Decimal | None = None
    preclose: Decimal | None = None
