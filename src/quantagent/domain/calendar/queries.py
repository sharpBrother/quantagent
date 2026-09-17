"""用 CalendarRepository 做研究读取。仓储已按 as_of 过滤，这里只跑规则。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.domain.calendar.rules import is_open, open_dates, shift_open
from quantagent.domain.errors import CalendarLookupError

if TYPE_CHECKING:
    from datetime import date

    from quantagent.domain.ports.calendar import CalendarRepository


class CalendarQueries:
    def __init__(self, repo: CalendarRepository) -> None:
        self._repo = repo

    def is_open(self, *, exchange: str, cal_dt: date, as_of: date) -> bool:
        days = self._repo.list_days(
            as_of=as_of,
            exchange=exchange,
            start=cal_dt,
            end=cal_dt,
        )
        return is_open(days, cal_dt)

    def trading_days(
        self,
        *,
        exchange: str,
        start: date,
        end: date,
        as_of: date,
    ) -> tuple[date, ...]:
        if start > end:
            raise CalendarLookupError("start 晚于 end")
        days = self._repo.list_days(
            as_of=as_of,
            exchange=exchange,
            start=start,
            end=end,
        )
        return open_dates(days)

    def shift(
        self,
        *,
        exchange: str,
        origin: date,
        n: int,
        as_of: date,
        start: date,
        end: date,
    ) -> date:
        """``start``/``end`` 是调用方给出的 observed domain，不能在规则里猜窗口。"""
        if start > end:
            raise CalendarLookupError("start 晚于 end")
        days = self._repo.list_days(
            as_of=as_of,
            exchange=exchange,
            start=start,
            end=end,
        )
        return shift_open(days, origin, n)
