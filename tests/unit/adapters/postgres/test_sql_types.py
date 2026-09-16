"""SQL Server → PostgreSQL 类型映射。"""

from __future__ import annotations

import pytest

from quantagent.adapters.postgres.sql_types import map_sql_server_type, quote_ident


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("varchar(8)", "varchar(8)"),
        ("varchar(max)", "text"),
        ("nvarchar(30)", "varchar(30)"),
        ("datetime", "timestamp"),
        ("datetime2(7)", "timestamp"),
        ("float", "double precision"),
        ("int", "integer"),
        ("tinyint", "smallint"),
        ("money", "numeric(19, 4)"),
        ("decimal(28, 6)", "numeric(28, 6)"),
        ("numeric(20, 4)", "numeric(20, 4)"),
        ("timestamp", "bytea"),
        ("rowversion", "bytea"),
    ],
)
def test_map_sql_server_type(raw: str, expected: str) -> None:
    assert map_sql_server_type(raw) == expected


@pytest.mark.unit
def test_unknown_sql_server_type_fails_closed() -> None:
    with pytest.raises(ValueError, match="未映射"):
        map_sql_server_type("geography")


@pytest.mark.unit
def test_quote_ident_preserves_case() -> None:
    assert quote_ident("ASHAREEODPRICES") == '"ASHAREEODPRICES"'
    assert quote_ident('weird"name') == '"weird""name"'
