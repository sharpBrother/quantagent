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
