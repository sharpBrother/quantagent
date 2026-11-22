from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pyarrow as pa
import pytest

from quantagent.ingest.errors import SourceFetchError
from quantagent.ingest.jobs.minprice import ingest_day
from quantagent.ingest.jobs.minprice_corrections import correct_known_row
from quantagent.ingest.jobs.minprice_validation import content_digest, validate_day
from quantagent.platform.config import Settings
from quantagent.platform.storage.paths import resolve_var_paths


def table(rows):
    schema = pa.schema(
        [
            ("ts_code", pa.string()),
            ("trade_time", pa.timestamp("us")),
            *[
                (name, pa.decimal128(20, 4))
                for name in ("open", "high", "low", "close", "vol", "amount")
            ],
        ]
    )
    return pa.Table.from_pylist(rows, schema=schema)


def row(**updates):
    result = {
        "ts_code": "920014.BJ",
        "trade_time": datetime(2025, 10, 28, 15),
        "open": Decimal("21"),
        "high": Decimal("21"),
        "low": Decimal("21"),
        "close": Decimal("21"),
        "vol": Decimal("-1"),
        "amount": Decimal("-21"),
    }
    result.update(updates)
    return result


def test_corrects_only_specified_values_without_mutating_source():
    original = table([row(), row(ts_code="000001.SZ", vol=Decimal("5"), amount=Decimal("100"))])
    result, details = correct_known_row(original, trade_date=date(2025, 10, 28), is_mysql=True)
    assert original["vol"].to_pylist() == [Decimal("-1"), Decimal("5")]
    assert result["vol"].to_pylist() == [Decimal("0"), Decimal("5")]
    assert result["amount"].to_pylist() == [Decimal("0"), Decimal("100")]
    assert details[0]["amount_before"] == "-21.0000"


@pytest.mark.parametrize("rows", [[], [row(vol=Decimal("-2"))], [row(), row()]])
def test_changed_missing_or_duplicate_target_stops(rows):
    with pytest.raises(SourceFetchError):
        correct_known_row(table(rows), trade_date=date(2025, 10, 28), is_mysql=True)


def test_does_not_correct_other_source_or_day():
    original = table([row()])
    for day, is_mysql in [(date(2025, 10, 28), False), (date(2025, 10, 29), True)]:
        result, details = correct_known_row(original, trade_date=day, is_mysql=is_mysql)
        assert result.equals(original)
        assert details == []


def test_november_correction_changes_only_target_amount():
    target = row(
        ts_code="600289.SH",
        trade_time=datetime(2025, 11, 26, 15),
        vol=Decimal("0"),
        amount=Decimal("-43"),
    )
    other = row(
        ts_code="000001.SZ",
        trade_time=datetime(2025, 11, 26, 15),
        vol=Decimal("5"),
        amount=Decimal("-1"),
    )
    original = table([target, other])
    result, details = correct_known_row(original, trade_date=date(2025, 11, 26), is_mysql=True)
    assert original["amount"].to_pylist() == [Decimal("-43"), Decimal("-1")]
    assert result["amount"].to_pylist() == [Decimal("0"), Decimal("-1")]
    assert result["vol"].to_pylist() == [Decimal("0"), Decimal("5")]
    assert details[0]["amount_before"] == "-43.0000"


@pytest.mark.parametrize("changes", [{"amount": Decimal("-42")}, {"vol": Decimal("1")}])
def test_november_changed_original_stops(changes):
    target = row(
        ts_code="600289.SH",
        trade_time=datetime(2025, 11, 26, 15),
        vol=Decimal("0"),
        amount=Decimal("-43"),
    )
    target.update(changes)
    with pytest.raises(SourceFetchError):
        correct_known_row(table([target]), trade_date=date(2025, 11, 26), is_mysql=True)


def test_december_correction_is_limited_to_specified_record():
    target = row(
        ts_code="920260.BJ",
        trade_time=datetime(2025, 12, 8, 15),
        vol=Decimal("0"),
        amount=Decimal("-3"),
    )
    other = row(
        ts_code="000001.SZ",
        trade_time=datetime(2025, 12, 8, 15),
        vol=Decimal("0"),
        amount=Decimal("-2"),
    )
    original = table([target, other])
    result, details = correct_known_row(original, trade_date=date(2025, 12, 8), is_mysql=True)
    assert original["amount"].to_pylist() == [Decimal("-3"), Decimal("-2")]
    assert result["amount"].to_pylist() == [Decimal("0"), Decimal("-2")]
    assert result["vol"].to_pylist() == [Decimal("0"), Decimal("0")]
    assert details[0]["amount_before"] == "-3.0000"


@pytest.mark.parametrize("changes", [{"amount": Decimal("-2")}, {"vol": Decimal("1")}])
def test_december_changed_original_stops(changes):
    target = row(
        ts_code="920260.BJ",
        trade_time=datetime(2025, 12, 8, 15),
        vol=Decimal("0"),
        amount=Decimal("-3"),
    )
    target.update(changes)
    with pytest.raises(SourceFetchError):
        correct_known_row(table([target]), trade_date=date(2025, 12, 8), is_mysql=True)


def test_ingest_records_raw_and_corrected_digests(monkeypatch, tmp_path):
    day = date(2025, 10, 28)
    source = row()
    rows = [
        tuple(
            source[key]
            for key in ("ts_code", "trade_time", "open", "high", "low", "close", "vol", "amount")
        )
    ]
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([rows]))
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.stage_partition",
        lambda corrected, **kw: SimpleNamespace(
            content_digest=content_digest(validate_day(corrected, trade_date=day))
        ),
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
    original = table([source]).append_column("trade_date", pa.array([day], type=pa.date32()))
    assert logs[0].input_digest == content_digest(original)
    assert logs[0].input_digest != logs[0].output_digest
    assert logs[0].source_corrections[0]["vol_before"] == "-1.0000"
