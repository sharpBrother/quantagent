"""日行情行。数值保持源端精度，缺失保持为空。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal


@dataclass(frozen=True, slots=True)
class DailyPrice:
    trade_dt: date
    wind_code: str
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: Decimal | None
    amount: Decimal | None
    pct_change: Decimal | None
    limit_up: Decimal | None = None
    limit_down: Decimal | None = None
    adj_close: Decimal | None = None
