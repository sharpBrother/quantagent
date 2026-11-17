"""回读按本页主键查，并且带批次条件。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from quantagent.adapters.postgres import src_write
from quantagent.adapters.postgres.src_targets import ASHAREEODPRICES
from quantagent.adapters.postgres.src_write import PostgresSrcStore
from quantagent.ingest.writers.tables import TRADE_CAL


@pytest.mark.unit
def test_readback_filters_by_batch_and_primary_key() -> None:
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [{"_row_hash": "a"}, {"_row_hash": "b"}]
    hashes = PostgresSrcStore(conn).readback_hashes(
        TRADE_CAL, 7, [("SSE", "20260105"), ("SZSE", "20260105")]
    )
    assert hashes == ["a", "b"]
    statement, params = cur.execute.call_args.args
    assert '"_batch_id" = %s' in statement
    assert '("exchange", "cal_date") IN (VALUES (%s, %s), (%s, %s))' in statement
    assert params == [7, "SSE", "20260105", "SZSE", "20260105"]


@pytest.mark.unit
def test_readback_chunks_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(src_write, "_KEY_CHUNK", 2)
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [{"_row_hash": "x"}]
    keys = [("SSE", f"2026010{day}") for day in range(5)]
    hashes = PostgresSrcStore(conn).readback_hashes(TRADE_CAL, 7, keys)
    assert cur.execute.call_count == 3
    assert hashes == ["x", "x", "x"]
    assert all(call.args[1][0] == 7 for call in cur.execute.call_args_list)


@pytest.mark.unit
def test_readback_without_keys_skips_query() -> None:
    conn = MagicMock()
    assert PostgresSrcStore(conn).readback_hashes(TRADE_CAL, 7, []) == []
    conn.cursor.assert_not_called()


@pytest.mark.unit
def test_mismatched_rows_sends_json_and_stays_read_only() -> None:
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [("oid-2",)]
    row = dict.fromkeys(ASHAREEODPRICES.native_columns)
    row.update(
        {"OBJECT_ID": "oid-2", "S_DQ_CLOSE": Decimal("10.5000"), "OPDATE": datetime(2026, 1, 2)}
    )
    assert PostgresSrcStore(conn).mismatched_rows(ASHAREEODPRICES, 7, [row]) == [("oid-2",)]
    statement, params = cur.execute.call_args.args
    assert statement.startswith("SELECT")
    assert "jsonb_populate_record" in statement
    assert '"10.5000"' in params[0]
    assert params[1] == 7
