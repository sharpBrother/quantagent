from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pyarrow as pa
import pytest

from quantagent.domain.minute_exclusions import JANUARY_21_EXCLUDED
from quantagent.ingest.errors import SourceFetchError, SourceNotReadyError
from quantagent.ingest.jobs.minprice import assert_daily_ready, ingest_day
from quantagent.platform.config import Settings
from quantagent.platform.storage.paths import resolve_var_paths


def test_dry_run_reads_source_without_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    row = (
        "000001.SZ",
        datetime(2026, 11, 20, 9, 30),
        *[Decimal("12")] * 4,
        Decimal("10"),
        Decimal("120"),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([[row]]))
    settings = Settings(var_root=tmp_path, allow_db_write=False)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    pg = MagicMock()
    result = ingest_day(
        MagicMock(),
        pg,
        trade_date=date(2026, 11, 20),
        settings=settings,
        paths=paths,
        calendar=MagicMock(),
    )
    assert result == "dry_run"
    pg.cursor.assert_not_called()
    assert not tmp_path.joinpath("lake").exists()


def test_empty_source_stops(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([]))
    settings = Settings(var_root=tmp_path, allow_db_write=False)
    with pytest.raises(SourceFetchError):
        ingest_day(
            MagicMock(),
            MagicMock(),
            trade_date=date(2024, 7, 29),
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            calendar=MagicMock(),
        )


def test_daily_ready_requires_close_and_previous_day_coverage() -> None:
    full = pa.table(
        {
            "ts_code": [f"{i:06d}.SZ" for i in range(95)],
            "trade_time": [datetime(2026, 11, 20, 15, 0)] * 95,
        }
    )
    assert_daily_ready(full, 100)
    with pytest.raises(SourceNotReadyError):
        assert_daily_ready(full, 101)
    partial = full.set_column(1, "trade_time", pa.array([datetime(2026, 11, 20, 14, 59)] * 95))
    with pytest.raises(SourceNotReadyError):
        assert_daily_ready(partial, 100)


def test_accepted_open_low_difference_is_recorded_in_run_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    row = (
        "000001.SZ",
        datetime(2026, 11, 20, 9, 31),
        Decimal("9.95"),
        Decimal("11"),
        Decimal("10"),
        Decimal("10.5"),
        Decimal("10"),
        Decimal("100"),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([[row]]))
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.stage_partition",
        lambda *a, **k: SimpleNamespace(content_digest="a" * 64),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.register_partition", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.persist_run_log", lambda record, paths: logs.append(record)
    )
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    assert (
        ingest_day(
            MagicMock(),
            pg,
            trade_date=date(2026, 11, 20),
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            calendar=MagicMock(),
            write_db=True,
        )
        == "inserted"
    )
    assert logs[0].tolerated_open_below_low == [
        {
            "ts_code": "000001.SZ",
            "trade_time": "2026-11-20 09:31:00",
            "open": "9.9500",
            "low": "10.0000",
        }
    ]


def test_january_21_excludes_affected_stocks_and_corrects_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    day = date(2026, 1, 21)
    codes = sorted(JANUARY_21_EXCLUDED)
    rows = []
    for code in codes:
        rows.append(
            (code, datetime(2026, 1, 21, 9, 30), *[Decimal("10")] * 4, Decimal("1"), Decimal("-1"))
        )
    for code in codes[:33]:
        rows.append(
            (code, datetime(2026, 1, 21, 9, 31), *[Decimal("10")] * 4, Decimal("1"), Decimal("-1"))
        )
    for code, minute in [("899002.BJ", 30), ("899002.BJ", 31), ("899050.BJ", 30)]:
        rows.append(
            (
                code,
                datetime(2026, 1, 21, 9, minute),
                *[Decimal("10")] * 4,
                Decimal("1"),
                Decimal("-1"),
            )
        )
    rows.append(
        (
            "000001.SZ",
            datetime(2026, 1, 21, 9, 30),
            *[Decimal("10")] * 4,
            Decimal("1"),
            Decimal("5"),
        )
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([rows]))
    captured: list[pa.Table] = []

    def stage(table: pa.Table, **kwargs: Any) -> SimpleNamespace:
        captured.append(table)
        return SimpleNamespace(content_digest="a" * 64)

    monkeypatch.setattr("quantagent.ingest.jobs.minprice.stage_partition", stage)
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.register_partition", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.persist_run_log", lambda record, paths: logs.append(record)
    )
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    assert (
        ingest_day(
            MagicMock(),
            pg,
            trade_date=day,
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            calendar=MagicMock(),
            write_db=True,
        )
        == "inserted"
    )
    assert set(captured[0]["ts_code"].to_pylist()) == {"000001.SZ", "899002.BJ", "899050.BJ"}
    assert len(logs[0].excluded_codes) == 67
    assert len(logs[0].source_corrections) == 3
    assert all(row["amount_after"] == "0.0000" for row in logs[0].source_corrections)


@pytest.mark.parametrize(
    ("day", "code", "negative"),
    [
        (date(2026, 1, 22), "002485.SZ", "-28"),
        (date(2026, 3, 26), "920242.BJ", "-31"),
        (date(2026, 4, 16), "920855.BJ", "-37"),
        (date(2026, 6, 8), "920608.BJ", "-51"),
        (date(2026, 6, 22), "920855.BJ", "-7"),
        (date(2026, 7, 8), "920132.BJ", "-56"),
    ],
)
def test_approved_negative_volume_corrected_after_daily_check(
    monkeypatch, tmp_path, day, code, negative
):
    rows = [
        (
            code,
            datetime.combine(day, datetime.min.time()).replace(hour=9, minute=30),
            *[Decimal("10")] * 4,
            Decimal("1"),
            Decimal("1000"),
        ),
        (
            code,
            datetime.combine(day, datetime.min.time()).replace(hour=15),
            *[Decimal("10")] * 4,
            Decimal("-1"),
            Decimal(negative),
        ),
    ]
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([rows]))
    captured = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.stage_partition",
        lambda table, **k: captured.append(table) or SimpleNamespace(content_digest="a" * 64),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.register_partition", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.persist_run_log", lambda record, paths: logs.append(record)
    )
    prices = MagicMock()
    prices.list_prices.return_value = [SimpleNamespace(wind_code=code, amount=Decimal("1"))]
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    kwargs = {
        "trade_date": day,
        "settings": settings,
        "paths": resolve_var_paths(settings, repo_root=tmp_path),
        "calendar": MagicMock(),
        "daily_prices": prices,
        "write_db": True,
    }
    assert ingest_day(MagicMock(), pg, **kwargs) == "inserted"
    result = captured[0].to_pylist()[1]
    assert result["vol"] == 0 and result["amount"] == 0
    assert logs[0].source_corrections[0]["vol_before"] == "-1.0000"
    assert logs[0].source_corrections[0]["amount_before"] == f"{Decimal(negative):.4f}"
    assert logs[0].input_digest != logs[0].output_digest
    prices.list_prices.return_value = [SimpleNamespace(wind_code=code, amount=Decimal("2"))]
    with pytest.raises(SourceFetchError, match="未通过成交额对比"):
        ingest_day(MagicMock(), pg, **kwargs)


@pytest.mark.parametrize(
    ("day", "code", "amount"),
    [
        (date(2026, 4, 30), "920608.BJ", "422"),
        (date(2026, 6, 2), "920112.BJ", "1037"),
        (date(2026, 6, 29), "920608.BJ", "11"),
        (date(2026, 7, 9), "920422.BJ", "337"),
        (date(2026, 7, 14), "920422.BJ", "11"),
        (date(2026, 7, 17), "920121.BJ", "2063"),
    ],
)
def test_corrects_approved_positive_amount_and_negative_volume(
    monkeypatch, tmp_path, day, code, amount
):
    row = (
        code,
        datetime.combine(day, datetime.min.time()).replace(hour=15),
        *[Decimal("10")] * 4,
        Decimal("-1"),
        Decimal(amount),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([[row]]))
    captured = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.stage_partition",
        lambda table, **k: captured.append(table) or SimpleNamespace(content_digest="a" * 64),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.register_partition", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.persist_run_log", lambda record, paths: logs.append(record)
    )
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    assert (
        ingest_day(
            MagicMock(),
            pg,
            trade_date=day,
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            calendar=MagicMock(),
            write_db=True,
        )
        == "inserted"
    )
    result = captured[0].to_pylist()[0]
    assert result["vol"] == 0 and result["amount"] == 0
    assert logs[0].source_corrections[0]["vol_before"] == "-1.0000"
    assert logs[0].source_corrections[0]["amount_before"] == f"{Decimal(amount):.4f}"
    assert logs[0].input_digest != logs[0].output_digest


def test_july_6_corrects_two_rows_with_distinct_amount_signs(monkeypatch, tmp_path):
    day = date(2026, 7, 6)
    rows = [
        (
            "920455.BJ",
            datetime(2026, 7, 6, 9, 30),
            *[Decimal("10")] * 4,
            Decimal("1"),
            Decimal("1000"),
        ),
        (
            "920455.BJ",
            datetime(2026, 7, 6, 15),
            *[Decimal("10")] * 4,
            Decimal("-1"),
            Decimal("-41"),
        ),
        (
            "920541.BJ",
            datetime(2026, 7, 6, 15),
            *[Decimal("10")] * 4,
            Decimal("-1"),
            Decimal("391"),
        ),
    ]
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([rows]))
    captured = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.stage_partition",
        lambda table, **k: captured.append(table) or SimpleNamespace(content_digest="a" * 64),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.register_partition", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.persist_run_log", lambda record, paths: logs.append(record)
    )
    prices = MagicMock()
    prices.list_prices.return_value = [SimpleNamespace(wind_code="920455.BJ", amount=Decimal("1"))]
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    assert (
        ingest_day(
            MagicMock(),
            pg,
            trade_date=day,
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            calendar=MagicMock(),
            daily_prices=prices,
            write_db=True,
        )
        == "inserted"
    )
    corrected = [r for r in captured[0].to_pylist() if r["trade_time"].hour == 15]
    assert len(corrected) == 2 and all(r["vol"] == 0 and r["amount"] == 0 for r in corrected)
    assert {(r["ts_code"], r["amount_before"]) for r in logs[0].source_corrections} == {
        ("920455.BJ", "-41.0000"),
        ("920541.BJ", "391.0000"),
    }
