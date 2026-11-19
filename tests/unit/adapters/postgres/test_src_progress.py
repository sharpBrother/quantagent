"""_batch 进度汇总：只读 SQL 与页速计算。"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from quantagent.adapters.postgres.src_progress import wind_progress


@pytest.mark.unit
def test_progress_is_read_only_and_computes_page_rate() -> None:
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [
        {
            "dataset": "src.wind.asharemoneyflow",
            "pages": 470,
            "rows": Decimal(4700000),
            "last_commit": datetime(2026, 11, 18, 9, 0, tzinfo=UTC),
            "source_cursor": '{"opdate":"2026-03-05T00:00:00","object_id":"x"}',
            "recent_pages": 11,
            "recent_span": Decimal(500),
        },
        {
            "dataset": "src.wind.asharecalendar",
            "pages": 32,
            "rows": Decimal(31483),
            "last_commit": datetime(2026, 11, 15, 9, 0, tzinfo=UTC),
            "source_cursor": None,
            "recent_pages": 0,
            "recent_span": None,
        },
    ]
    rows = wind_progress(conn, window_minutes=60)
    statement, params = cur.execute.call_args.args
    assert statement.lstrip().upper().startswith("SELECT")
    for verb in ("INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE"):
        assert verb not in statement.upper()
    assert params == {"window": 60}
    assert rows[0].rows == 4700000
    assert rows[0].recent_seconds_per_page == 50.0
    assert rows[1].recent_seconds_per_page is None
