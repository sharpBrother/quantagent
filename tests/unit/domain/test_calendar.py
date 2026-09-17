"""日历规则在已过滤的行上工作，不读存储。"""

from __future__ import annotations

from datetime import date

import pytest

from quantagent.domain.calendar.queries import CalendarQueries
from quantagent.domain.calendar.rules import is_open, shift_open
from quantagent.domain.calendar.types import CalendarDay
from quantagent.domain.errors import CalendarLookupError, EmptyDomainError


def _days() -> tuple[CalendarDay, ...]:
    return (
        CalendarDay(date(2026, 9, 11), "SSE", True, date(2026, 9, 10)),
        CalendarDay(date(2026, 9, 12), "SSE", False, date(2026, 9, 11)),
        CalendarDay(date(2026, 9, 13), "SSE", False, date(2026, 9, 11)),
        CalendarDay(date(2026, 9, 14), "SSE", True, date(2026, 9, 11)),
        CalendarDay(date(2026, 9, 15), "SSE", True, date(2026, 9, 14)),
    )


class _Repo:
    def __init__(self, rows: tuple[CalendarDay, ...]) -> None:
        self.rows = rows

    def list_days(
        self,
        *,
        as_of: date,
        exchange: str,
        start: date,
        end: date,
    ) -> tuple[CalendarDay, ...]:
        matched = tuple(
            row for row in self.rows if row.exchange == exchange and start <= row.cal_dt <= end
        )
        if not matched:
            raise EmptyDomainError("empty")
        return matched


@pytest.mark.unit
def test_is_open_false_on_visible_holiday() -> None:
    assert is_open(_days(), date(2026, 9, 12)) is False
    assert is_open(_days(), date(2026, 9, 14)) is True


@pytest.mark.unit
def test_missing_day_fail_closed() -> None:
    with pytest.raises(CalendarLookupError, match="不可见或缺失"):
        is_open(_days(), date(2026, 9, 20))


@pytest.mark.unit
def test_shift_skips_holidays_and_does_not_invent_future() -> None:
    days = _days()
    assert shift_open(days, date(2026, 9, 11), 1) == date(2026, 9, 14)
    assert shift_open(days, date(2026, 9, 14), -1) == date(2026, 9, 11)
    assert shift_open(days, date(2026, 9, 14), 0) == date(2026, 9, 14)
    with pytest.raises(CalendarLookupError, match=r"T\+0"):
        shift_open(days, date(2026, 9, 12), 0)
    with pytest.raises(CalendarLookupError, match="超出"):
        shift_open(days, date(2026, 9, 15), 1)


@pytest.mark.unit
def test_queries_delegate_to_repo_window() -> None:
    queries = CalendarQueries(_Repo(_days()))
    as_of = date(2026, 9, 15)
    assert queries.is_open(exchange="SSE", cal_dt=date(2026, 9, 12), as_of=as_of) is False
    assert queries.shift(
        exchange="SSE",
        origin=date(2026, 9, 11),
        n=1,
        as_of=as_of,
        start=date(2026, 9, 11),
        end=date(2026, 9, 15),
    ) == date(2026, 9, 14)
    assert queries.trading_days(
        exchange="SSE",
        start=date(2026, 9, 11),
        end=date(2026, 9, 15),
        as_of=as_of,
    ) == (date(2026, 9, 11), date(2026, 9, 14), date(2026, 9, 15))
