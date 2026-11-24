"""前瞻收益物化的股票池按截面日 all_a 取，不用 end 日成员回填整个区间。
区间中途退出 all_a 的股票，在退出前的信号日仍要产出；退出后的信号日不产出。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from quantagent.adapters.lake.trade_calendar import load_trade_calendar_visibility
from quantagent.adapters.memory.calendar import MemoryCalendarRepository
from quantagent.adapters.memory.prices import MemoryDailyPriceRepository
from quantagent.adapters.postgres.daily_prices import load_price_visibility
from quantagent.cli._universe import in_membership, keep_rows_in_membership, union_codes
from quantagent.domain.calendar import CalendarDay
from quantagent.domain.forward_return import ForwardReturn
from quantagent.domain.prices.types import DailyPrice
from quantagent.lake.materialize.forward_return import select_forward_returns

if TYPE_CHECKING:
    from collections.abc import Sequence


def _calendar(first: date, count: int) -> tuple[CalendarDay, ...]:
    """按自然日生成交易日历，周末休市。"""
    rows: list[CalendarDay] = []
    day = first
    for _ in range(count):
        rows.append(
            CalendarDay(
                cal_dt=day,
                exchange="SSE",
                is_open=day.weekday() < 5,
                prev_trade_dt=None,
            )
        )
        day = date.fromordinal(day.toordinal() + 1)
    return tuple(rows)


def _price(day: date, code: str) -> DailyPrice:
    return DailyPrice(
        trade_dt=day,
        wind_code=code,
        open=Decimal("1"),
        high=Decimal("1"),
        low=Decimal("1"),
        close=Decimal("1"),
        volume=Decimal("1"),
        amount=Decimal("1"),
        pct_change=None,
        adj_open=Decimal("10"),
        trade_status_code=1,
    )


def _opens(days: Sequence[CalendarDay]) -> tuple[date, ...]:
    return tuple(day.cal_dt for day in days if day.is_open)


@pytest.mark.unit
def test_union_codes_across_signal_dates_is_sorted() -> None:
    members = {
        date(2024, 3, 1): frozenset({"600000.SH", "000001.SZ"}),
        date(2024, 3, 4): frozenset({"000001.SZ", "300001.SZ"}),
    }
    assert union_codes(members) == ("000001.SZ", "300001.SZ", "600000.SH")


@pytest.mark.unit
def test_in_membership_fails_closed_for_days_outside_map() -> None:
    members = {date(2024, 3, 1): frozenset({"000001.SZ"})}
    keep = in_membership(members)
    row = ForwardReturn(
        asset_id="000001.SZ",
        event_dt=date(2024, 3, 5),
        horizon="1d",
        return_kind="total",
        benchmark_id="none",
        value=0.0,
        end_dt=date(2024, 3, 6),
        knowledge_dt=date(2024, 3, 6),
        pit_grade="A",
        return_leg="open2open",
        start_dt=date(2024, 3, 5),
    )
    # 截面日不在映射里时不产出，不猜测成员关系。
    assert keep(row) is False
    assert keep_rows_in_membership((row,), members) == ()


@pytest.mark.unit
def test_stock_leaving_all_a_mid_range_keeps_only_signal_dates_before_exit() -> None:
    days = _calendar(date(2024, 3, 1), 60)
    opens = _opens(days)
    start, end = opens[0], opens[29]
    exit_index = 15
    # X 在第 exit_index 个信号日之前属于 all_a，之后仍有行情但不再是成员。Y 全程属于 all_a。
    members_by_day = {
        day: frozenset({"000001.SZ", "000002.SZ"})
        if index <= exit_index
        else frozenset({"000001.SZ"})
        for index, day in enumerate(opens[:30])
    }
    prices = [_price(day, code) for day in opens for code in ("000001.SZ", "000002.SZ")]

    result = select_forward_returns(
        calendar=MemoryCalendarRepository(days, contract=load_trade_calendar_visibility()),
        prices=MemoryDailyPriceRepository(prices, contract=load_price_visibility()),
        contract=load_price_visibility(),
        start=start,
        end=end,
        as_of=opens[-1],
        wind_codes=union_codes(members_by_day),
        horizons=("1d",),
        keep_row=in_membership(members_by_day),
    )

    x_events = sorted(row.event_dt for row in result if row.asset_id == "000002.SZ")
    # 退出前的信号日都产出；退出后的信号日不产出。
    assert x_events == list(opens[: exit_index + 1])
    y_events = sorted(row.event_dt for row in result if row.asset_id == "000001.SZ")
    assert y_events == list(opens[:30])


@pytest.mark.unit
def test_without_keep_row_every_read_code_is_emitted() -> None:
    """对照组：不传过滤时，读取并集里的股票在退出后的信号日仍会产出。这正是需要过滤的原因。"""
    days = _calendar(date(2024, 3, 1), 60)
    opens = _opens(days)
    members_by_day = {
        day: frozenset({"000001.SZ", "000002.SZ"}) if index <= 15 else frozenset({"000001.SZ"})
        for index, day in enumerate(opens[:30])
    }
    prices = [_price(day, code) for day in opens for code in ("000001.SZ", "000002.SZ")]

    result = select_forward_returns(
        calendar=MemoryCalendarRepository(days, contract=load_trade_calendar_visibility()),
        prices=MemoryDailyPriceRepository(prices, contract=load_price_visibility()),
        contract=load_price_visibility(),
        start=opens[0],
        end=opens[29],
        as_of=opens[-1],
        wind_codes=union_codes(members_by_day),
        horizons=("1d",),
    )

    x_events = sorted(row.event_dt for row in result if row.asset_id == "000002.SZ")
    assert x_events[-1] == opens[29]
