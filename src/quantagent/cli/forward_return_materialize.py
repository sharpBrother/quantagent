"""组装前瞻收益物化：接上 PG 行情、lake 日历和 all_a 默认代码池，业务规则不在这里。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.daily_prices import (
    PostgresDailyPriceRepository,
    load_price_visibility,
)
from quantagent.cli._universe import all_a_members_by_day, in_membership, union_codes
from quantagent.domain.calendar import open_dates
from quantagent.lake.materialize.forward_return import EXCHANGE, materialize_forward_return
from quantagent.platform.pg import connect

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

    from quantagent.domain.forward_return import ForwardReturn
    from quantagent.domain.ports.calendar import CalendarRepository
    from quantagent.lake.materialize.forward_return import ForwardReturnWriteResult
    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths


def materialize_forward_return_cli(
    *,
    settings: Settings,
    paths: VarPaths,
    start: date,
    end: date,
    as_of: date,
    wind_codes: tuple[str, ...] | None,
) -> ForwardReturnWriteResult:
    """``wind_codes`` 为 ``None`` 时，按每个信号日取 all_a 成员：读取范围取各信号日成员的并集，
    输出只保留信号日当天属于 all_a 的行。区间中途退出 all_a 的股票，在退出前的信号日仍产出，
    退出后不产出；不用 ``end`` 日成员回填整个区间，否则会造成幸存者偏差。
    """
    calendar = LakeCalendarRepository(paths.lake / "std" / "trade_calendar")
    conn = connect(settings, "src")
    try:
        conn.read_only = True
        keep_row: Callable[[ForwardReturn], bool] | None = None
        if wind_codes:
            codes = wind_codes
        else:
            days = _signal_dates(calendar, as_of=as_of, start=start, end=end)
            members_by_day = all_a_members_by_day(conn, as_of=as_of, days=days)
            codes = union_codes(members_by_day)
            keep_row = in_membership(members_by_day)
        return materialize_forward_return(
            paths=paths,
            calendar=calendar,
            prices=PostgresDailyPriceRepository(conn, contract=load_price_visibility()),
            contract=load_price_visibility(),
            start=start,
            end=end,
            as_of=as_of,
            wind_codes=codes,
            keep_row=keep_row,
        )
    finally:
        conn.close()


def _signal_dates(
    calendar: CalendarRepository, *, as_of: date, start: date, end: date
) -> tuple[date, ...]:
    """信号日与 ``select_forward_returns`` 一致：``[start, min(end, as_of)]`` 内的 SSE 开市日。
    ``start`` 晚于上界时返回空元组，由 ``select_forward_returns`` 报出原有的区间错误。
    """
    last = min(end, as_of)
    if start > last:
        return ()
    days = calendar.list_days(as_of=as_of, exchange=EXCHANGE, start=start, end=as_of)
    return tuple(day for day in open_dates(days) if start <= day <= last)
