"""PostgreSQL ST 适配器：假连接，只验证 SQL 形态、PIT 截止与失败路径。"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from quantagent.adapters.postgres.st import PostgresStStatusRepository
from quantagent.domain.errors import InvalidQueryError

AS_OF = date(2024, 1, 31)


def _conn(fetched: list[dict[str, object]] | None = None) -> MagicMock:
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = fetched or []
    return conn


def _row(code: object, entry: object, remove: object) -> dict[str, object]:
    return {"S_INFO_WINDCODE": code, "ENTRY_DT": entry, "REMOVE_DT": remove}


@pytest.mark.unit
def test_st_is_read_with_readonly_sql_and_dt_parameter() -> None:
    conn = _conn([_row("000001.SZ", "20240110", None)])
    result = PostgresStStatusRepository(conn).st_codes_at(as_of=AS_OF, dt=date(2024, 1, 31))

    assert result == frozenset({"000001.SZ"})
    cur = conn.cursor.return_value.__enter__.return_value
    assert cur.execute.call_count == 1
    statement, params = cur.execute.call_args.args
    assert statement.lstrip().upper().startswith("SELECT")
    for verb in ("UPDATE", "INSERT", "DELETE", "MERGE", "TRUNCATE", "DROP", "ALTER"):
        assert verb not in statement.upper()
    assert '"src_wind"."ASHAREST"' in statement
    assert '"ENTRY_DT" <= %s OR "ENTRY_DT" IS NULL' in statement
    assert params == ("20240131",)


@pytest.mark.unit
def test_dt_after_as_of_fails_without_touching_db() -> None:
    conn = _conn()
    with pytest.raises(InvalidQueryError):
        PostgresStStatusRepository(conn).st_codes_at(as_of=AS_OF, dt=date(2024, 2, 1))
    conn.cursor.assert_not_called()


@pytest.mark.unit
def test_empty_result_is_empty_set_not_error() -> None:
    conn = _conn([])
    assert PostgresStStatusRepository(conn).st_codes_at(as_of=AS_OF, dt=AS_OF) == frozenset()


@pytest.mark.unit
def test_remove_on_dt_is_not_st_and_overlap_is_deduplicated() -> None:
    conn = _conn(
        [
            _row("000002.SZ", "20240101", "20240131"),
            _row("000002.SZ", "20240115", None),
            _row("000003.SZ", "20240101", "20240131"),
        ]
    )
    result = PostgresStStatusRepository(conn).st_codes_at(as_of=AS_OF, dt=AS_OF)
    assert result == frozenset({"000002.SZ"})


@pytest.mark.unit
@pytest.mark.parametrize("entry", ["2024-01-01", "20241301", "", "abcdefgh", 20240101])
def test_illegal_entry_dt_is_invalid(entry: object) -> None:
    conn = _conn([_row("000001.SZ", entry, None)])
    with pytest.raises(InvalidQueryError):
        PostgresStStatusRepository(conn).st_codes_at(as_of=AS_OF, dt=AS_OF)


@pytest.mark.unit
@pytest.mark.parametrize("remove", ["2024-02-01", "20240230", "", 20240201])
def test_illegal_remove_dt_is_invalid(remove: object) -> None:
    conn = _conn([_row("000001.SZ", "20240101", remove)])
    with pytest.raises(InvalidQueryError):
        PostgresStStatusRepository(conn).st_codes_at(as_of=AS_OF, dt=AS_OF)


@pytest.mark.unit
def test_null_entry_dt_from_db_is_invalid() -> None:
    conn = _conn([_row("000001.SZ", None, None)])
    with pytest.raises(InvalidQueryError):
        PostgresStStatusRepository(conn).st_codes_at(as_of=AS_OF, dt=AS_OF)


@pytest.mark.unit
@pytest.mark.parametrize("code", [None, "", "   "])
def test_blank_code_is_invalid(code: object) -> None:
    conn = _conn([_row(code, "20240101", None)])
    with pytest.raises(InvalidQueryError):
        PostgresStStatusRepository(conn).st_codes_at(as_of=AS_OF, dt=AS_OF)


@pytest.mark.unit
def test_remove_before_entry_is_invalid() -> None:
    conn = _conn([_row("000001.SZ", "20240110", "20240105")])
    with pytest.raises(InvalidQueryError):
        PostgresStStatusRepository(conn).st_codes_at(as_of=AS_OF, dt=AS_OF)
