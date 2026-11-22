from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from quantagent.adapters.lake.minute_bar import LakeMinuteBarRepository
from quantagent.domain.calendar.types import CalendarDay
from quantagent.domain.errors import EmptyDomainError


def test_reader_checks_manifest_and_footer(tmp_path):
    day = date(2026, 11, 20)
    file = tmp_path / "a.parquet"
    pq.write_table(
        pa.table({"ts_code": ["000001.SZ"], "trade_time": [datetime(2026, 11, 20, 15)]}), file
    )
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cal = SimpleNamespace(list_days=lambda **kw: (CalendarDay(day, "SSE", True, None),))
    repo = LakeMinuteBarRepository(conn, tmp_path, cal)
    cur.fetchall.return_value = [(day, "a.parquet", 1)]
    result = repo.scan_window(
        as_of=day, start=day, end=day, codes=["000001.SZ"], columns=["ts_code"]
    )
    assert result["ts_code"].to_pylist() == ["000001.SZ"]
    cur.fetchall.return_value = [(day, "a.parquet", 2)]
    with pytest.raises(ValueError, match="footer"):
        repo.scan_window(as_of=day, start=day, end=day)
    cur.fetchall.return_value = []
    with pytest.raises(EmptyDomainError, match="manifest"):
        repo.scan_window(as_of=day, start=day, end=day)


def test_reader_rejects_future_window(tmp_path):
    day = date(2026, 11, 20)
    repo = LakeMinuteBarRepository(MagicMock(), tmp_path, MagicMock())
    with pytest.raises(EmptyDomainError):
        repo.scan_window(as_of=date(2026, 11, 19), start=day, end=day)
