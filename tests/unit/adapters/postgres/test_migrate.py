"""迁移运行器：文件名、动词白名单、checksum 守卫。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from psycopg.conninfo import conninfo_to_dict

from quantagent.adapters.postgres.errors import MigrationError
from quantagent.adapters.postgres.migrate import (
    apply_migrations,
    assert_migration_sql,
    list_migration_files,
    resolve_planes,
    split_sql_statements,
)
from quantagent.platform.config.settings import Settings
from quantagent.platform.errors import ConfigError, WriteGateError
from quantagent.platform.pg import dsn_for

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_split_sql_ignores_comment_lines() -> None:
    sql = """
-- 注释
CREATE SCHEMA ops;

CREATE TABLE ops.x (
    id integer PRIMARY KEY
);
"""
    statements = split_sql_statements(sql)
    assert statements == (
        "CREATE SCHEMA ops",
        "CREATE TABLE ops.x (\n    id integer PRIMARY KEY\n)",
    )


@pytest.mark.unit
def test_empty_table_rebuild_must_create_the_same_table() -> None:
    assert_migration_sql(
        """
        DROP TABLE src_wind."AINDEXEODPRICES";
        CREATE TABLE src_wind."AINDEXEODPRICES" (id integer PRIMARY KEY);
        """,
        filename="rebuild.sql",
    )
    with pytest.raises(MigrationError, match="没有在同一文件重建"):
        assert_migration_sql(
            'DROP TABLE src_wind."AINDEXEODPRICES";',
            filename="rebuild.sql",
        )


def test_assert_migration_sql_rejects_drop() -> None:
    with pytest.raises(MigrationError, match="动词非法"):
        assert_migration_sql("DROP TABLE src_wind.x;", filename="x.sql")


@pytest.mark.unit
def test_assert_migration_sql_rejects_insert() -> None:
    with pytest.raises(MigrationError, match=r"动词非法|禁止动词"):
        assert_migration_sql("INSERT INTO qa_migrate.applied VALUES (1);", filename="x.sql")


@pytest.mark.unit
def test_resolve_planes() -> None:
    assert resolve_planes("all") == ("src", "ops")
    assert resolve_planes("src") == ("src",)
    with pytest.raises(MigrationError, match="plane"):
        resolve_planes("lake")


@pytest.mark.unit
def test_list_migration_files_on_repo(repo_root: Path) -> None:
    src = list_migration_files(repo_root, "src")
    ops = list_migration_files(repo_root, "ops")
    assert [item.filename for item in src] == [
        "0001_schemas.sql",
        "0002_batch.sql",
        "0003_wind.sql",
        "0004_tushare.sql",
        "0005_jydb.sql",
        "0006_suntime.sql",
        "0007_macro.sql",
        "0008_wind_asharecalendar.sql",
        "0009_aindexeodprices_source_columns.sql",
        "0010_asharemoneyflow_source_columns.sql",
        "0011_src_batch_id_indexes.sql",
        "0012_aindexvaluation_source_columns.sql",
        "0013_aindexmembers_source_columns.sql",
        "0014_swindexmembers_source_columns.sql",
        "0015_aindexindustrieseodcitics_source_columns.sql",
        "0016_asharedividend_source_columns.sql",
        "0017_rebuilt_tables_batch_id_indexes.sql",
    ]
    assert [item.filename for item in ops] == [
        "0001_schema.sql",
        "0002_dagster_storage.sql",
    ]
    assert all(item.checksum for item in (*src, *ops))


@pytest.mark.unit
def test_apply_migrations_requires_configuration(repo_root: Path) -> None:
    settings = Settings(_env_file=None)
    with pytest.raises(MigrationError, match="未配置"):
        apply_migrations(
            settings=settings,
            repo_root=repo_root,
            planes=("src",),
            write_db=False,
        )


@pytest.mark.unit
def test_apply_migrations_requires_write_gate(repo_root: Path) -> None:
    settings = Settings(
        _env_file=None,
        pg_src_database="quantagent",
        pg_src_user="qa",
        allow_db_write=False,
    )
    with pytest.raises(WriteGateError, match="QUANTAGENT_ALLOW_DB_WRITE"):
        apply_migrations(
            settings=settings,
            repo_root=repo_root,
            planes=("src",),
            write_db=True,
        )


@pytest.mark.unit
def test_on_delete_cascade_is_not_dml() -> None:
    assert_migration_sql(
        "CREATE TABLE ops.run_tags (run_id varchar REFERENCES ops.runs (run_id) ON DELETE CASCADE)",
        filename="fk.sql",
    )


@pytest.mark.unit
def test_delete_statement_is_still_rejected() -> None:
    with pytest.raises(MigrationError, match="语句动词非法"):
        assert_migration_sql("DELETE FROM ops.runs", filename="delete.sql")


@pytest.mark.unit
def test_src_dsn_requires_configuration() -> None:
    settings = Settings(_env_file=None)
    with pytest.raises(ConfigError, match="研究数据面未配置"):
        dsn_for(settings, "src")


@pytest.mark.unit
def test_src_dsn_contains_database() -> None:
    settings = Settings(_env_file=None, pg_src_database="quantagent_src", pg_src_user="qa")
    info = conninfo_to_dict(dsn_for(settings, "src"))
    assert info["dbname"] == "quantagent_src"
    assert info["user"] == "qa"
