from datetime import date, datetime
from decimal import Decimal

import pyarrow as pa
import pytest

from quantagent.ingest.errors import SourceFetchError
from quantagent.ingest.jobs.minprice_validation import content_digest, validate_day

DAY = date(2026, 11, 20)


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
    values = {
        "ts_code": "000001.SZ",
        "trade_time": datetime(2026, 11, 20, 9, 30),
        "open": Decimal("12"),
        "high": Decimal("13"),
        "low": Decimal("11"),
        "close": Decimal("12"),
        "vol": Decimal("10"),
        "amount": Decimal("1200"),
    }
    values.update(updates)
    return values


def test_valid_and_digest_independent_of_row_order_and_chunks():
    a = row()
    b = row(trade_time=datetime(2026, 11, 20, 9, 31))
    first = validate_day(table([a, b]), trade_date=DAY)
    second = validate_day(pa.concat_tables([table([b]), table([a])]), trade_date=DAY)
    assert content_digest(first) == content_digest(second)
    assert first["trade_date"].to_pylist() == [DAY, DAY]


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [row(), row()],
        [row(trade_time=datetime(2026, 11, 19, 9, 30))],
        [row(trade_time=datetime(2026, 11, 20, 12, 0))],
        [row(close=Decimal("14"))],
        [row(vol=Decimal("-1"))],
        [row(open=None)],
    ],
)
def test_rejects_invalid_rows(rows):
    with pytest.raises(SourceFetchError):
        validate_day(table(rows), trade_date=DAY)


@pytest.mark.parametrize("open_price", ["10.0000", "9.9900", "9.9500"])
def test_open_low_tolerance_is_inclusive_and_preserves_source(open_price):
    source = row(
        open=Decimal(open_price),
        low=Decimal("10.0000"),
        close=Decimal("10.5000"),
        high=Decimal("11.0000"),
    )
    result = validate_day(table([source]), trade_date=DAY)
    assert result["open"].to_pylist() == [Decimal(open_price)]
    assert result["low"].to_pylist() == [Decimal("10.0000")]


def test_open_low_gap_over_threshold_is_rejected():
    source = row(
        open=Decimal("9.9499"),
        low=Decimal("10.0000"),
        close=Decimal("10.5000"),
        high=Decimal("11.0000"),
    )
    with pytest.raises(SourceFetchError, match=r"0\.5%"):
        validate_day(table([source]), trade_date=DAY)


def test_tolerance_does_not_apply_to_close_or_high():
    for overrides in ({"close": Decimal("9.9900")}, {"high": Decimal("9.9900")}):
        source = row(open=Decimal("9.9900"), low=Decimal("10.0000"), **overrides)
        with pytest.raises(SourceFetchError):
            validate_day(table([source]), trade_date=DAY)
