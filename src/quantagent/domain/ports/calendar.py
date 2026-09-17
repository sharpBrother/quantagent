"""交易日历仓储。只取回 as_of 可见的日历行；T+N 在 domain.calendar。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date

    from quantagent.domain.calendar.types import CalendarDay


class CalendarRepository(Protocol):
    def list_days(
        self,
        *,
        as_of: date,
        exchange: str,
        start: date,
        end: date,
    ) -> tuple[CalendarDay, ...]:
        """``[start, end]`` 内、``as_of`` 可见的日历行。

        无行则 ``EmptyDomainError``。不提供省略 ``as_of`` 的重载。
        """
        ...
