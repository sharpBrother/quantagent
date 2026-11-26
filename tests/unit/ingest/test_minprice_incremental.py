from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from quantagent.domain.calendar.types import CalendarDay
from quantagent.ingest.errors import SourceNotReadyError
from quantagent.ingest.jobs.minprice_incremental import ingest_mysql_incremental
from quantagent.platform.config import Settings
from quantagent.platform.storage.paths import resolve_var_paths


def test_incremental_catches_up_missing_days_with_previous_count(
    monkeypatch, tmp_path: Path
) -> None:
    d24, d25, d26 = date(2026, 11, 24), date(2026, 11, 25), date(2026, 11, 26)
    calendar = SimpleNamespace(
        list_days=lambda **kw: (
            CalendarDay(d25, "SSE", True, d24),
            CalendarDay(d26, "SSE", True, d25),
        )
    )
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.side_effect = [(d24,), (5581,), (5579,)]
    mysql = MagicMock()
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice_incremental.list_tables",
        lambda *a, **kw: ("m20261125", "m20261126"),
    )
    calls = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice_incremental.ingest_day",
        lambda *a, **kw: calls.append(kw) or "inserted",
    )
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    result = ingest_mysql_incremental(
        mysql,
        pg,
        as_of=d26,
        settings=settings,
        paths=resolve_var_paths(settings, repo_root=tmp_path),
        calendar=calendar,
        daily_prices=MagicMock(),
        write_db=True,
    )
    assert result == "inserted"
    assert [(x["trade_date"], x["previous_code_count"]) for x in calls] == [
        (d25, 5581),
        (d26, 5579),
    ]
    assert all(x["write_db"] for x in calls)


def test_missing_source_stops_before_writing(monkeypatch, tmp_path: Path) -> None:
    day = date(2026, 11, 26)
    calendar = SimpleNamespace(
        list_days=lambda **kw: (CalendarDay(day, "SSE", True, date(2026, 11, 25)),)
    )
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = (date(2026, 11, 25),)
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice_incremental.list_tables", lambda *a, **kw: ()
    )
    ingest = MagicMock()
    monkeypatch.setattr("quantagent.ingest.jobs.minprice_incremental.ingest_day", ingest)
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    with pytest.raises(SourceNotReadyError, match="尚未就绪"):
        ingest_mysql_incremental(
            MagicMock(),
            pg,
            as_of=day,
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            calendar=calendar,
            daily_prices=MagicMock(),
            write_db=True,
        )
    ingest.assert_not_called()


def test_current_partition_is_not_written_again(tmp_path: Path) -> None:
    day = date(2026, 11, 26)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = (day,)
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    assert (
        ingest_mysql_incremental(
            MagicMock(),
            pg,
            as_of=day,
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            calendar=MagicMock(),
            daily_prices=MagicMock(),
            write_db=True,
        )
        == "up_to_date"
    )
