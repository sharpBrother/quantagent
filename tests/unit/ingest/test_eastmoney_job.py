from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from quantagent.domain.calendar.types import CalendarDay
from quantagent.ingest.errors import SourceFetchError
from quantagent.ingest.jobs.eastmoney_minute import ingest_eastmoney_day
from quantagent.platform.config import Settings
from quantagent.platform.identity import digest_file
from quantagent.platform.storage.paths import resolve_var_paths


def test_daily_uses_previous_manifest_and_records_eastmoney(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    day = date(2026, 11, 20)
    previous = date(2026, 11, 19)
    calendar = SimpleNamespace(list_days=lambda **kw: (CalendarDay(day, "SSE", True, previous),))
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.side_effect = [None, (100,)]
    monkeypatch.setattr(
        "quantagent.ingest.jobs.eastmoney_minute.list_stocks", lambda: ("000001.SZ",)
    )
    seen: dict[str, Any] = {}

    def ingest(*args: Any, **kwargs: Any) -> str:
        seen.update(kwargs)
        return "inserted"

    monkeypatch.setattr("quantagent.ingest.jobs.eastmoney_minute.ingest_day", ingest)
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    assert (
        ingest_eastmoney_day(
            pg,
            trade_date=day,
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            calendar=calendar,
            write_db=True,
        )
        == "inserted"
    )
    assert seen["source_table"] == "eastmoney.trends2"
    assert seen["previous_code_count"] == 100


def test_daily_rejects_missing_previous_day(tmp_path: Path) -> None:
    day = date(2026, 11, 20)
    calendar = SimpleNamespace(
        list_days=lambda **kw: (CalendarDay(day, "SSE", True, date(2026, 11, 19)),)
    )
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    settings = Settings(var_root=tmp_path)
    with pytest.raises(SourceFetchError, match="上一交易日"):
        ingest_eastmoney_day(
            pg,
            trade_date=day,
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            calendar=calendar,
        )


def test_daily_skips_verified_existing_partition_without_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    day = date(2026, 11, 20)
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    root = paths.lake / "src/minprice/ashare_minute_bar"
    root.mkdir(parents=True)
    file = root / "part.parquet"
    pq.write_table(pa.table({"x": [1]}), file)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = (
        "part.parquet",
        1,
        digest_file(file),
    )
    monkeypatch.setattr(
        "quantagent.ingest.jobs.eastmoney_minute.list_stocks", lambda: pytest.fail("不应重新请求")
    )
    assert (
        ingest_eastmoney_day(
            pg, trade_date=day, settings=settings, paths=paths, calendar=MagicMock(), write_db=True
        )
        == "skipped"
    )
