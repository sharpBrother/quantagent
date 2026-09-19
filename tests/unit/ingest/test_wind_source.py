"""Wind 复合游标、分页 SQL、中文修复。"""

from __future__ import annotations

from datetime import datetime

import pytest

from quantagent.ingest.errors import SourceFetchError, TargetNotAllowedError
from quantagent.ingest.sources.wind.cursor import (
    WindCursor,
    cursor_from_row,
    decode_cursor,
    initial_cursor,
)
from quantagent.ingest.sources.wind.decode import decode_chi_row, decode_chi_value
from quantagent.ingest.sources.wind.paged import build_page_sql
from quantagent.ingest.sources.wind.tables import resolve_wind_paged_table
from quantagent.ingest.writers.tables import ASHAREEODPRICES


@pytest.mark.unit
def test_initial_cursor_is_epoch() -> None:
    cursor = initial_cursor()
    assert cursor.opdate == datetime(1900, 1, 1)
    assert cursor.object_id == ""
    assert decode_cursor(None) == cursor
    assert decode_cursor(cursor.encode()) == cursor


@pytest.mark.unit
def test_decode_cursor_rejects_garbage() -> None:
    with pytest.raises(SourceFetchError, match="无法解析"):
        decode_cursor("not-json")
    with pytest.raises(SourceFetchError, match="缺 opdate"):
        decode_cursor('{"opdate":1,"object_id":"x"}')


@pytest.mark.unit
def test_cursor_from_row_requires_datetime() -> None:
    with pytest.raises(SourceFetchError, match="OPDATE"):
        cursor_from_row({"OPDATE": "2024-01-01", "OBJECT_ID": "a"})
    row = {"OPDATE": datetime(2024, 1, 2, 15, 1, 2), "OBJECT_ID": "oid-1"}
    assert cursor_from_row(row) == WindCursor(datetime(2024, 1, 2, 15, 1, 2), "oid-1")


@pytest.mark.unit
def test_page_sql_uses_composite_key_and_excludes_nulls() -> None:
    sql = build_page_sql(
        table="ASHAREEODPRICES",
        columns=("OBJECT_ID", "OPDATE", "gsUTime"),
        limit=1000,
    )
    assert "SELECT TOP (1000)" in sql
    assert "[dbo].[ASHAREEODPRICES]" in sql
    assert "[OPDATE] IS NOT NULL" in sql
    assert "[OBJECT_ID] IS NOT NULL" in sql
    assert "[OPDATE] > %s" in sql
    assert "[OBJECT_ID] > %s" in sql
    assert "ORDER BY [OPDATE], [OBJECT_ID]" in sql


@pytest.mark.unit
def test_page_sql_rejects_injection() -> None:
    with pytest.raises(SourceFetchError, match="表名非法"):
        build_page_sql(table="ASHAREEODPRICES; DROP TABLE x", columns=("OBJECT_ID",), limit=10)
    with pytest.raises(SourceFetchError, match="列名非法"):
        build_page_sql(table="ASHAREEODPRICES", columns=("OBJECT_ID;1",), limit=10)
    with pytest.raises(SourceFetchError, match="page size"):
        build_page_sql(table="ASHAREEODPRICES", columns=("OBJECT_ID",), limit=0)


@pytest.mark.unit
def test_chi_decode_latin1_gbk_and_idempotent_unicode() -> None:
    garbled = "停牌".encode("gbk").decode("latin1")
    assert decode_chi_value(garbled) == "停牌"
    assert decode_chi_value("停牌") == "停牌"
    patched = decode_chi_row({"S_DQ_TRADESTATUS": garbled, "X": 1}, ("S_DQ_TRADESTATUS",))
    assert patched["S_DQ_TRADESTATUS"] == "停牌"
    assert patched["X"] == 1


@pytest.mark.unit
def test_only_ashareeodprices_is_whitelisted() -> None:
    table = resolve_wind_paged_table("ASHAREEODPRICES")
    assert table.spec == ASHAREEODPRICES
    assert table.chi_fields == ("S_DQ_TRADESTATUS",)
    with pytest.raises(TargetNotAllowedError, match="白名单"):
        resolve_wind_paged_table("AINDEXEODPRICES")
