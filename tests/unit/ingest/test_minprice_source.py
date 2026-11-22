from unittest.mock import MagicMock

import pytest

from quantagent.ingest.errors import SourceFetchError
from quantagent.ingest.sources.minprice import list_tables, read_day


def test_lists_only_valid_tables():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.__iter__.return_value = iter([("m20261120",), ("bad",), ("m20261119",)])
    assert list_tables(conn, database="minprice") == ("m20261119", "m20261120")


@pytest.mark.parametrize("table", ["m20261120; DROP TABLE x", "m20261121", "other"])
def test_rejects_unlisted_or_unsafe_tables(table):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.__iter__.return_value = iter([("m20261120",)])
    with pytest.raises(SourceFetchError):
        list(read_day(conn, database="minprice", table=table))


def test_reads_in_bounded_batches():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.__iter__.return_value = iter([("m20261120",)])
    cur.fetchmany.side_effect = [[("first",)], [("second",)], []]
    assert list(read_day(conn, database="minprice", table="m20261120", batch_size=1)) == [
        [("first",)],
        [("second",)],
    ]
