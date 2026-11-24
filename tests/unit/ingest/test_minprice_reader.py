from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from quantagent.adapters.lake.minute_bar import LakeMinuteBarRepository
from quantagent.domain.calendar.types import CalendarDay
from quantagent.domain.errors import EmptyDomainError
from quantagent.domain.minute_exclusions import JANUARY_21_EXCLUDED


def test_reader_checks_manifest_and_footer(tmp_path: Path) -> None:
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


def test_reader_rejects_future_window(tmp_path: Path) -> None:
    day = date(2026, 11, 20)
    repo = LakeMinuteBarRepository(MagicMock(), tmp_path, MagicMock())
    with pytest.raises(EmptyDomainError):
        repo.scan_window(as_of=date(2026, 11, 19), start=day, end=day)


def test_partial_day_rejects_full_market_and_excluded_code(tmp_path: Path) -> None:
    day = date(2026, 1, 21)
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = [(day, "a.parquet", 1)]
    cal = SimpleNamespace(list_days=lambda **kw: (CalendarDay(day, "SSE", True, None),))
    repo = LakeMinuteBarRepository(conn, tmp_path, cal)
    with pytest.raises(EmptyDomainError, match="不含已排除股票"):
        repo.scan_window(as_of=day, start=day, end=day)
    with pytest.raises(EmptyDomainError, match="不含已排除股票"):
        repo.scan_window(as_of=day, start=day, end=day, codes=["002067.SZ"])


def test_excluded_codes_union_footer_list_and_january_21_constant(tmp_path: Path) -> None:
    # 排除集从分区 footer 与 2026-01-21 的已裁定名单取得；无元数据的日子只有已裁定名单。
    day = date(2026, 1, 19)
    table = pa.table({"ts_code": ["000001.SZ"], "trade_time": [datetime(2026, 1, 19, 15)]})
    table = table.replace_schema_metadata({b"quantagent.excluded_codes": b'["000002.SZ"]'})
    pq.write_table(table, tmp_path / "partial.parquet")
    pq.write_table(table.replace_schema_metadata({}), tmp_path / "plain.parquet")
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = LakeMinuteBarRepository(conn, tmp_path, MagicMock())

    cur.fetchall.return_value = [(day, "partial.parquet", 1)]
    assert repo.excluded_codes(as_of=day, day=day) == frozenset({"000002.SZ"})

    cur.fetchall.return_value = [(date(2026, 1, 21), "plain.parquet", 1)]
    got = repo.excluded_codes(as_of=date(2026, 1, 21), day=date(2026, 1, 21))
    assert got == JANUARY_21_EXCLUDED
    assert "002067.SZ" in got


def test_excluded_codes_rejects_day_after_visibility(tmp_path: Path) -> None:
    day = date(2026, 11, 20)
    repo = LakeMinuteBarRepository(MagicMock(), tmp_path, MagicMock())
    with pytest.raises(EmptyDomainError):
        repo.excluded_codes(as_of=date(2026, 11, 19), day=day)


def test_reader_respects_embedded_exclusion_list(tmp_path: Path) -> None:
    day = date(2026, 1, 19)
    table = pa.table({"ts_code": ["000001.SZ"], "trade_time": [datetime(2026, 1, 19, 15)]})
    table = table.replace_schema_metadata({b"quantagent.excluded_codes": b'["000002.SZ"]'})
    pq.write_table(table, tmp_path / "partial.parquet")
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = [
        (day, "partial.parquet", 1)
    ]
    cal = SimpleNamespace(list_days=lambda **kw: (CalendarDay(day, "SSE", True, None),))
    repo = LakeMinuteBarRepository(conn, tmp_path, cal)
    with pytest.raises(EmptyDomainError, match="不含已排除股票"):
        repo.scan_window(as_of=day, start=day, end=day)
    with pytest.raises(EmptyDomainError, match="不含已排除股票"):
        repo.scan_window(as_of=day, start=day, end=day, codes=["000002.SZ"])
    assert (
        repo.scan_window(
            as_of=day, start=day, end=day, codes=["000001.SZ"], columns=["ts_code"]
        ).num_rows
        == 1
    )
