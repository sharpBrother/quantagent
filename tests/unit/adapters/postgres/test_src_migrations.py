"""第一批 src_* 迁移 SQL 与清单一致。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from quantagent.adapters.postgres.migrate import list_migration_files, split_sql_statements
from quantagent.adapters.postgres.src_catalog import load_src_tables

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_keep_list_tables_are_created(repo_root: Path) -> None:
    tables = load_src_tables(repo_root)
    assert len(tables) == 59
    sql = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((repo_root / "db" / "migrations" / "src").glob("*.sql"))
    )
    for table in tables:
        needle = f'CREATE TABLE {table.schema}."{table.name}"'
        assert needle in sql, needle


@pytest.mark.unit
def test_source_schemas_and_batch_tables_exist(repo_root: Path) -> None:
    sql = (repo_root / "db" / "migrations" / "src" / "0001_schemas.sql").read_text(encoding="utf-8")
    batch = (repo_root / "db" / "migrations" / "src" / "0002_batch.sql").read_text(encoding="utf-8")
    for schema in ("src_wind", "src_tushare", "src_jydb", "src_suntime", "src_macro"):
        assert f"CREATE SCHEMA {schema};" in sql
        assert f"CREATE TABLE {schema}._batch (" in batch


@pytest.mark.unit
def test_tech_columns_and_quoted_native_names(repo_root: Path) -> None:
    wind = (repo_root / "db" / "migrations" / "src" / "0003_wind.sql").read_text(encoding="utf-8")
    assert '"OBJECT_ID" varchar(100) NOT NULL' in wind
    assert '"GSUPDTIME" bytea' in wind
    assert "_batch_id bigint NOT NULL REFERENCES src_wind._batch (_batch_id)" in wind
    assert "_ingested_at timestamptz NOT NULL" in wind
    assert "_row_hash char(64) NOT NULL" in wind
    tushare = (repo_root / "db" / "migrations" / "src" / "0004_tushare.sql").read_text(
        encoding="utf-8"
    )
    assert 'PRIMARY KEY ("exchange", "cal_date")' in tushare
    macro = (repo_root / "db" / "migrations" / "src" / "0007_macro.sql").read_text(encoding="utf-8")
    assert '"yield" numeric(18, 3) NOT NULL' in macro


@pytest.mark.unit
def test_src_sql_has_no_drop_or_dml(repo_root: Path) -> None:
    files = list_migration_files(repo_root, "src")
    statements: list[str] = []
    for item in files:
        statements.extend(split_sql_statements(item.path.read_text(encoding="utf-8")))
    assert statements
    assert all(stmt.split(None, 1)[0].upper() == "CREATE" for stmt in statements)


@pytest.mark.unit
def test_ops_sql_creates_schema_only(repo_root: Path) -> None:
    text = (repo_root / "db" / "migrations" / "ops" / "0001_schema.sql").read_text(encoding="utf-8")
    assert "CREATE SCHEMA ops;" in text
    assert "CREATE TABLE" not in text
