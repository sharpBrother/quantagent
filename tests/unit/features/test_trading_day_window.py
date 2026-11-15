"""最近 N 个交易日：不补空档，截面日缺失就是缺失。"""

from __future__ import annotations

from datetime import date

import pytest

from quantagent.domain.errors import FeatureLookupError
from quantagent.features.window import last_n_trading_days


def _day(value: str) -> date:
    return date.fromisoformat(value)


@pytest.mark.unit
def test_last_n_days_stop_at_event_and_skip_gaps() -> None:
    rows = (
        (_day("2024-01-02"), "d2"),
        (_day("2024-01-04"), "d4"),
        (_day("2024-01-05"), "d5"),
        (_day("2024-01-08"), "later"),
    )
    window = last_n_trading_days(
        rows,
        event_dt=_day("2024-01-05"),
        count=3,
        trade_dt=lambda item: item[0],
    )
    assert window is not None
    assert [item[1] for item in window] == ["d2", "d4", "d5"]


@pytest.mark.unit
def test_missing_event_or_short_history_returns_none() -> None:
    rows = (_day("2024-01-02"), _day("2024-01-03"))
    assert (
        last_n_trading_days(
            rows,
            event_dt=_day("2024-01-04"),
            count=1,
            trade_dt=lambda item: item,
        )
        is None
    )
    assert (
        last_n_trading_days(
            rows,
            event_dt=_day("2024-01-03"),
            count=3,
            trade_dt=lambda item: item,
        )
        is None
    )


@pytest.mark.unit
def test_duplicate_trade_date_fails() -> None:
    rows = ((_day("2024-01-02"), 1), (_day("2024-01-02"), 2))
    with pytest.raises(FeatureLookupError, match="交易日重复"):
        last_n_trading_days(
            rows,
            event_dt=_day("2024-01-02"),
            count=1,
            trade_dt=lambda item: item[0],
        )


@pytest.mark.unit
def test_count_must_be_positive() -> None:
    with pytest.raises(FeatureLookupError, match="交易日窗口"):
        last_n_trading_days(
            (),
            event_dt=_day("2024-01-02"),
            count=0,
            trade_dt=lambda item: item,
        )
