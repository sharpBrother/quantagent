"""物化读取起点要盖住第一个截面日往前 68 个开市日。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from quantagent.cli.tr_umr_materialize import _read_start
from quantagent.features.library.price.tr_umr import LOOKBACK


def _days(count: int) -> tuple[date, ...]:
    start = date(2024, 1, 1)
    return tuple(start + timedelta(days=offset) for offset in range(count))


@pytest.mark.unit
def test_read_start_covers_sixty_eight_open_days_before_first_event() -> None:
    opens = _days(100)
    start = opens[80]
    assert _read_start(opens, start=start, end=opens[90]) == opens[80 - (LOOKBACK - 1)]
    assert _read_start(opens, start=opens[10], end=opens[20]) == opens[0]
    assert _read_start(opens, start=date(2025, 1, 1), end=date(2025, 1, 2)) == date(2025, 1, 1)
