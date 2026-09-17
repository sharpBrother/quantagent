"""交易日历行。形状与 ``std.trade_calendar`` 对齐，不含存储字段。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date


@dataclass(frozen=True)
class CalendarDay:
    cal_dt: date
    exchange: str
    is_open: bool
    prev_trade_dt: date | None
