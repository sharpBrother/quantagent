"""日历规则：在已经 PIT 过滤过的行上做开市判断与 T+N。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.domain.errors import CalendarLookupError, EmptyDomainError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from quantagent.domain.calendar.types import CalendarDay


def require_unique_days(days: Sequence[CalendarDay]) -> dict[date, CalendarDay]:
    by_dt: dict[date, CalendarDay] = {}
    for row in days:
        if row.cal_dt in by_dt:
            raise CalendarLookupError(f"日历键重复: {row.exchange} {row.cal_dt.isoformat()}")
        by_dt[row.cal_dt] = row
    if not by_dt:
        raise EmptyDomainError("日历查询域为空")
    return by_dt


def is_open(days: Sequence[CalendarDay], cal_dt: date) -> bool:
    by_dt = require_unique_days(days)
    row = by_dt.get(cal_dt)
    if row is None:
        raise CalendarLookupError(f"日历日不可见或缺失: {cal_dt.isoformat()}")
    return row.is_open


def open_dates(days: Sequence[CalendarDay]) -> tuple[date, ...]:
    by_dt = require_unique_days(days)
    return tuple(dt for dt in sorted(by_dt) if by_dt[dt].is_open)


def shift_open(days: Sequence[CalendarDay], origin: date, n: int) -> date:
    """相对 ``origin`` 的第 n 个开市日。n=0 要求 origin 本身开市。

    n>0 为 origin 之后（不含当日），n<0 为之前。超出可见开市日则失败，
    不循环到域外、不借用不可见的未来日历。
    """
    opens = open_dates(days)
    if n == 0:
        if origin not in opens:
            raise CalendarLookupError(f"T+0 不是开市日: {origin.isoformat()}")
        return origin
    after = [dt for dt in opens if dt > origin]
    before = [dt for dt in opens if dt < origin]
    if n > 0:
        if n > len(after):
            raise CalendarLookupError(f"T+{n} 超出可见开市日: origin={origin.isoformat()}")
        return after[n - 1]
    needed = -n
    if needed > len(before):
        raise CalendarLookupError(f"T{n} 超出可见开市日: origin={origin.isoformat()}")
    return before[-needed]
