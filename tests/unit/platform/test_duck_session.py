"""DuckDB 会话只连内存，并把 parquet 挂成视图。"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from quantagent.platform.duck import duck_session, open_session, register_parquet
from quantagent.platform.errors import DuckSessionError

if TYPE_CHECKING:
    from pathlib import Path


def _one_row_parquet(path: Path) -> None:
    table = pa.table(
        {
            "event_dt": pa.array([date(2024, 1, 2)], type=pa.date32()),
            "value": pa.array([1.0]),
        }
    )
    pq.write_table(table, path)


@pytest.mark.unit
def test_session_does_not_create_duckdb_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with duck_session(memory_limit="256MB", threads=1) as conn:
        listed = conn.execute("PRAGMA database_list").fetchall()
        assert listed[0][1] == "memory"
        assert listed[0][2] is None
        conn.execute("SELECT 1").fetchone()
    assert list(tmp_path.rglob("*.duckdb")) == []


@pytest.mark.unit
def test_register_parquet_directory_and_query(tmp_path: Path) -> None:
    _one_row_parquet(tmp_path / "part-00000.parquet")
    with duck_session() as conn:
        register_parquet(conn, "sample", tmp_path)
        assert conn.execute("SELECT count(*) FROM sample").fetchone() == (1,)


@pytest.mark.unit
def test_register_parquet_empty_dir_fails_closed(tmp_path: Path) -> None:
    empty = tmp_path / "lake"
    empty.mkdir()
    with duck_session() as conn, pytest.raises(DuckSessionError, match="没有 parquet"):
        register_parquet(conn, "sample", empty)


@pytest.mark.unit
def test_invalid_view_name_rejected(tmp_path: Path) -> None:
    _one_row_parquet(tmp_path / "a.parquet")
    with duck_session() as conn, pytest.raises(DuckSessionError, match="非法"):
        register_parquet(conn, "feature-value", tmp_path / "a.parquet")


@pytest.mark.unit
def test_invalid_memory_limit_rejected() -> None:
    with pytest.raises(DuckSessionError, match="memory_limit"):
        open_session(memory_limit="lots")
