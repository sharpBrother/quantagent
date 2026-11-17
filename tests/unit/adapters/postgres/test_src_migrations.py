"""第一批 src_* 迁移 SQL 与清单一致。"""

from __future__ import annotations

import re
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
    assert '"yield" numeric(18, 3) NOT NULL' in tushare
    assert 'CREATE TABLE src_tushare."eco_cal"' in tushare
    suntime = (repo_root / "db" / "migrations" / "src" / "0006_suntime.sql").read_text(
        encoding="utf-8"
    )
    assert 'CREATE TABLE src_suntime."FIN_APPO_RELE_DATE"' in suntime
    assert 'CREATE TABLE src_wind."FIN_APPO_RELE_DATE"' not in wind
    macro = (repo_root / "db" / "migrations" / "src" / "0007_macro.sql").read_text(encoding="utf-8")
    assert "macro_eco_cal" not in macro


@pytest.mark.unit
def test_every_batch_id_column_is_indexed(repo_root: Path) -> None:
    # 外键列不会自动建索引。新表带 _batch_id 时必须在迁移里补上索引。
    files = list_migration_files(repo_root, "src")
    statements: list[str] = []
    for item in files:
        statements.extend(split_sql_statements(item.path.read_text(encoding="utf-8")))
    with_batch = {
        match.group(1)
        for stmt in statements
        if (match := re.match(r"CREATE TABLE (src_\w+\.\"[^\"]+\")", stmt)) is not None
        and "_batch_id bigint NOT NULL REFERENCES" in stmt
    }
    indexed = {
        match.group(1)
        for stmt in statements
        if (
            match := re.match(
                r"CREATE INDEX \"[^\"]+\" ON (src_\w+\.\"[^\"]+\") \(_batch_id\)$", stmt
            )
        )
        is not None
    }
    assert len(with_batch) == 60
    assert with_batch - indexed == set()


# 历史例外：0003 已应用后发现两张空表多建了源端没有的列，0009/0010 删表重建。
# 两条都已在库里执行，迁移不重跑，表现在已有数据。只放行这两条、且只放行
# 删除随后在同文件重建的那张表；之后的源面迁移仍只能是 CREATE（AGENTS.md §6.3）。
_HISTORICAL_DROP_REBUILD = {
    "0009_aindexeodprices_source_columns.sql": 'src_wind."AINDEXEODPRICES"',
    "0010_asharemoneyflow_source_columns.sql": 'src_wind."ASHAREMONEYFLOW"',
    "0012_aindexvaluation_source_columns.sql": 'src_wind."AINDEXVALUATION"',
    "0013_aindexmembers_source_columns.sql": 'src_wind."AINDEXMEMBERS"',
    "0014_swindexmembers_source_columns.sql": 'src_wind."SWINDEXMEMBERS"',
    "0015_aindexindustrieseodcitics_source_columns.sql": 'src_wind."AINDEXINDUSTRIESEODCITICS"',
    "0016_asharedividend_source_columns.sql": 'src_wind."ASHAREDIVIDEND"',
}


@pytest.mark.unit
def test_src_sql_has_no_drop_or_dml(repo_root: Path) -> None:
    files = list_migration_files(repo_root, "src")
    statements: list[str] = []
    for item in files:
        file_statements = split_sql_statements(item.path.read_text(encoding="utf-8"))
        rebuilt = _HISTORICAL_DROP_REBUILD.get(item.path.name)
        if rebuilt is not None:
            assert file_statements[0] == f"DROP TABLE {rebuilt}", item.path.name
            assert file_statements[1].startswith(f"CREATE TABLE {rebuilt} ("), item.path.name
            file_statements = file_statements[1:]
        statements.extend(file_statements)
    assert statements
    assert all(stmt.split(None, 1)[0].upper() == "CREATE" for stmt in statements)


@pytest.mark.unit
def test_ops_sql_creates_schema_only(repo_root: Path) -> None:
    text = (repo_root / "db" / "migrations" / "ops" / "0001_schema.sql").read_text(encoding="utf-8")
    assert "CREATE SCHEMA ops;" in text
    assert "CREATE TABLE" not in text
