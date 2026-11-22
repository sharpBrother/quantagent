from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pyarrow as pa
import pytest

import quantagent.ingest.jobs.minprice_corrections as corrections
from quantagent.ingest.errors import SourceFetchError
from quantagent.ingest.jobs.minprice import _SCHEMA, ingest_day
from quantagent.ingest.jobs.minprice_corrections import (
    correct_known_row,
    reconcile_negative_amounts,
)
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


def test_does_not_correct_other_source():
    original = table([row()])
    result, details = correct_known_row(original, trade_date=date(2025, 10, 28), is_mysql=False)
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
    assert result["amount"].to_pylist() == [Decimal("0"), Decimal("0")]
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
    assert result["amount"].to_pylist() == [Decimal("0"), Decimal("0")]
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


def test_december_11_correction_only_changes_target():
    target = row(
        ts_code="600165.SH",
        trade_time=datetime(2025, 12, 11, 15),
        vol=Decimal("0"),
        amount=Decimal("-56"),
    )
    other = row(
        ts_code="000001.SZ",
        trade_time=datetime(2025, 12, 11, 15),
        vol=Decimal("0"),
        amount=Decimal("-1"),
    )
    original = table([target, other])
    result, details = correct_known_row(original, trade_date=date(2025, 12, 11), is_mysql=True)
    assert original["amount"].to_pylist() == [Decimal("-56"), Decimal("-1")]
    assert result["amount"].to_pylist() == [Decimal("0"), Decimal("0")]
    assert result["vol"].to_pylist() == [Decimal("0"), Decimal("0")]
    assert details[0]["amount_before"] == "-56.0000"


@pytest.mark.parametrize("changes", [{"amount": Decimal("-55")}, {"vol": Decimal("1")}])
def test_december_11_changed_original_stops(changes):
    target = row(
        ts_code="600165.SH",
        trade_time=datetime(2025, 12, 11, 15),
        vol=Decimal("0"),
        amount=Decimal("-56"),
    )
    target.update(changes)
    with pytest.raises(SourceFetchError):
        correct_known_row(table([target]), trade_date=date(2025, 12, 11), is_mysql=True)


def test_december_29_correction_only_changes_target():
    target = row(
        ts_code="002898.SZ",
        trade_time=datetime(2025, 12, 29, 15),
        vol=Decimal("0"),
        amount=Decimal("-94"),
    )
    other = row(
        ts_code="000001.SZ",
        trade_time=datetime(2025, 12, 29, 15),
        vol=Decimal("0"),
        amount=Decimal("-2"),
    )
    original = table([target, other])
    result, details = correct_known_row(original, trade_date=date(2025, 12, 29), is_mysql=True)
    assert original["amount"].to_pylist() == [Decimal("-94"), Decimal("-2")]
    assert result["amount"].to_pylist() == [Decimal("0"), Decimal("0")]
    assert result["vol"].to_pylist() == [Decimal("0"), Decimal("0")]
    assert details[0]["amount_before"] == "-94.0000"


@pytest.mark.parametrize("changes", [{"amount": Decimal("-93")}, {"vol": Decimal("1")}])
def test_december_29_changed_original_stops(changes):
    target = row(
        ts_code="002898.SZ",
        trade_time=datetime(2025, 12, 29, 15),
        vol=Decimal("0"),
        amount=Decimal("-94"),
    )
    target.update(changes)
    with pytest.raises(SourceFetchError):
        correct_known_row(table([target]), trade_date=date(2025, 12, 29), is_mysql=True)


@pytest.mark.parametrize("count", [1, 10])
def test_general_mysql_negative_amount_correction(count):
    day = date(2026, 1, 5)
    records = [
        row(
            ts_code=f"{i:06d}.SZ",
            trade_time=datetime(2026, 1, 5, 9, 31),
            vol=Decimal("0"),
            amount=Decimal("-2"),
        )
        for i in range(count)
    ]
    original = table(records)
    corrected, details = correct_known_row(original, trade_date=day, is_mysql=True)
    assert original["amount"].to_pylist() == [Decimal("-2")] * count
    assert corrected["amount"].to_pylist() == [Decimal("0")] * count
    assert len(details) == count
    assert all(item["amount_before"] == "-2.0000" for item in details)


def test_general_correction_rejects_more_than_ten():
    day = date(2026, 1, 5)
    records = [
        row(
            ts_code=f"{i:06d}.SZ",
            trade_time=datetime(2026, 1, 5, 9, 31),
            vol=Decimal("0"),
            amount=Decimal("-2"),
        )
        for i in range(11)
    ]
    with pytest.raises(SourceFetchError, match="10"):
        correct_known_row(table(records), trade_date=day, is_mysql=True)


def test_october_17_approved_records_only(monkeypatch):
    day = date(2025, 10, 17)
    records = [
        row(
            ts_code=f"{i:06d}.SZ",
            trade_time=datetime(2025, 10, 17, 13, 30),
            vol=Decimal("1"),
            amount=Decimal("-2"),
        )
        for i in range(45)
    ]
    original = table(records)
    monkeypatch.setattr(
        corrections, "_APPROVED_FINGERPRINT", corrections._negative_rows_fingerprint(original)
    )
    result, details = correct_known_row(original, trade_date=day, is_mysql=True)
    assert result["amount"].to_pylist() == [Decimal("0")] * 45
    assert len(details) == 45
    altered = [*records]
    altered[0] = {**altered[0], "amount": Decimal("-3")}
    with pytest.raises(SourceFetchError, match="不一致"):
        correct_known_row(table(altered), trade_date=day, is_mysql=True)
    with pytest.raises(SourceFetchError, match="不一致"):
        correct_known_row(table(records[:-1]), trade_date=day, is_mysql=True)


def test_january_13_approved_records_only(monkeypatch):
    day = date(2026, 1, 13)
    records = [
        row(
            ts_code=f"{i:06d}.SZ",
            trade_time=datetime(2026, 1, 13, 13, 30),
            vol=Decimal("1"),
            amount=Decimal("-2"),
        )
        for i in range(75)
    ]
    original = table(records)
    monkeypatch.setattr(
        corrections, "_JANUARY_FINGERPRINT", corrections._negative_rows_fingerprint(original)
    )
    result, details = correct_known_row(original, trade_date=day, is_mysql=True)
    assert result["amount"].to_pylist() == [Decimal("0")] * 75
    assert len(details) == 75
    altered = [*records]
    altered[0] = {**altered[0], "amount": Decimal("-3")}
    with pytest.raises(SourceFetchError, match="不一致"):
        correct_known_row(table(altered), trade_date=day, is_mysql=True)
    with pytest.raises(SourceFetchError, match="不一致"):
        correct_known_row(table(records[:-1]), trade_date=day, is_mysql=True)


def test_general_correction_does_not_fix_negative_volume():
    day = date(2026, 1, 5)
    original = table(
        [
            row(
                ts_code="000001.SZ",
                trade_time=datetime(2026, 1, 5, 9, 31),
                vol=Decimal("-1"),
                amount=Decimal("-2"),
            )
        ]
    )
    corrected, details = correct_known_row(original, trade_date=day, is_mysql=True)
    assert corrected["vol"].to_pylist() == [Decimal("-1")]
    assert details[0]["vol_after"] == "-1.0000"
    with pytest.raises(SourceFetchError, match="vol"):
        validate_day(corrected, trade_date=day)


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


def test_reconcile_negative_amounts_applies_strict_half_percent_and_missing():
    day = date(2026, 1, 19)

    def record(code, minute, amount):
        return (
            code,
            datetime(2026, 1, 19, 9, minute),
            *[Decimal("10")] * 4,
            Decimal("1"),
            Decimal(amount),
        )

    rows = [record(code, 30, "-1") for code in ("A", "B", "C", "D")]
    rows += [
        record("A", 31, "1004"),
        record("B", 31, "1005"),
        record("C", 31, "995"),
        record("D", 31, "1000"),
    ]
    table = pa.Table.from_pylist(
        [dict(zip(_SCHEMA.names, row, strict=True)) for row in rows], schema=_SCHEMA
    )
    prices = MagicMock()
    prices.list_prices.return_value = [
        SimpleNamespace(wind_code=code, amount=Decimal("1")) for code in ("A", "B", "C")
    ]
    result, corrections, excluded, decisions = reconcile_negative_amounts(
        table, trade_date=day, prices=prices
    )
    assert set(result["ts_code"].to_pylist()) == {"A"}
    assert excluded == ["B", "C", "D"]
    assert len(corrections) == 1
    assert len(decisions) == 4
    prices.list_prices.assert_called_once_with(
        as_of=day, start=day, end=day, wind_codes=("A", "B", "C", "D")
    )
