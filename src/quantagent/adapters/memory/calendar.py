"""std.trade_calendar 的内存实现。与 lake 适配器跑同一套契约测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.domain.errors import CalendarLookupError, EmptyDomainError
from quantagent.domain.pit import is_point_event_visible

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.calendar.types import CalendarDay


class MemoryCalendarRepository:
    def __init__(
        self,
        rows: Sequence[CalendarDay],
        *,
        contract: VisibilityContract,
    ) -> None:
        self._rows = tuple(rows)
        self._contract = contract

    def list_days(
        self,
        *,
        as_of: date,
        exchange: str,
        start: date,
        end: date,
    ) -> tuple[CalendarDay, ...]:
        if not exchange.strip():
            raise CalendarLookupError("exchange 为空")
        if start > end:
            raise CalendarLookupError("start 晚于 end")
        matched = [
            row
            for row in self._rows
            if row.exchange == exchange
            and start <= row.cal_dt <= end
            and is_point_event_visible(self._contract, event_dt=row.cal_dt, as_of=as_of)
        ]
        if not matched:
            raise EmptyDomainError(
                f"日历域为空: exchange={exchange} start={start.isoformat()} "
                f"end={end.isoformat()} as_of={as_of.isoformat()}"
            )
        return tuple(sorted(matched, key=lambda row: row.cal_dt))
