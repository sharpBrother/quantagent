"""成员区间闭区间：OUTDATE 当天仍在池内。"""

from __future__ import annotations

from datetime import date

from quantagent.domain.universe import interval_contains


def test_open_ended_interval_contains() -> None:
    assert interval_contains(valid_from=date(2024, 1, 2), valid_to=None, dt=date(2024, 6, 1))
    assert not interval_contains(valid_from=date(2024, 1, 2), valid_to=None, dt=date(2024, 1, 1))


def test_closed_interval_includes_valid_to() -> None:
    assert interval_contains(
        valid_from=date(2024, 1, 2),
        valid_to=date(2024, 3, 1),
        dt=date(2024, 3, 1),
    )
    assert not interval_contains(
        valid_from=date(2024, 1, 2),
        valid_to=date(2024, 3, 1),
        dt=date(2024, 3, 2),
    )


def test_entry_day_is_included() -> None:
    assert interval_contains(
        valid_from=date(2024, 1, 2), valid_to=date(2024, 3, 1), dt=date(2024, 1, 2)
    )
