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


_MACRO_DROPS = """
DROP TABLE src_macro."macro_jin10_usa_ism_pmi";
DROP TABLE src_macro."macro_gpr_daily";
DROP TABLE src_macro."macro_fred_observation";
CREATE TABLE src_macro."gpr_daily" (id integer PRIMARY KEY);
"""


_BOND_FX_TABLES = (
    'src_wind."CBONDCURVECNBD"',
    'src_wind."CBONDCURVECSI"',
    'src_wind."CBONDREPOANDIBLEODPRICES"',
    'src_wind."CBONDPRICESREPO"',
    'src_wind."CBONDREPO"',
    'src_wind."FXEODPRICES"',
)


@pytest.mark.unit
def test_bond_fx_rebuild_requires_each_drop_followed_by_same_create() -> None:
    adjacent = "\n".join(
        f"DROP TABLE {name};\nCREATE TABLE {name} (id integer PRIMARY KEY);"
        for name in _BOND_FX_TABLES
    )
    assert_migration_sql(adjacent, filename="0019_bond_fx_wind_tables.sql")
    # 一条 CREATE INDEX 夹在 DROP 与 CREATE 之间，就不再是紧跟，必须拒绝。
    separated = adjacent.replace(
        f"DROP TABLE {_BOND_FX_TABLES[0]};\n",
        f'DROP TABLE {_BOND_FX_TABLES[0]};\nCREATE INDEX "x" ON src_wind.y (_batch_id);\n',
    )
    with pytest.raises(MigrationError, match="紧跟同名 CREATE"):
        assert_migration_sql(separated, filename="0019_bond_fx_wind_tables.sql")
    # 白名单之外的表不能借这个文件删除。
    with pytest.raises(MigrationError, match="白名单"):
        assert_migration_sql(
            'DROP TABLE src_wind."AINDEXEODPRICES";\n'
            'CREATE TABLE src_wind."AINDEXEODPRICES" (id integer PRIMARY KEY);',
            filename="0019_bond_fx_wind_tables.sql",
        )


_VIEW_SWAP = """
DROP TABLE src_wind."AINDEXINDUSTRIESCITICS";
CREATE VIEW src_wind."AINDEXINDUSTRIESCITICS" AS SELECT 1 AS "OBJECT_ID";
"""


@pytest.mark.unit
def test_drop_table_then_create_view_is_allowed_only_for_0020() -> None:
    assert_migration_sql(_VIEW_SWAP, filename="0020_aindexdescription.sql")
    # 同样的文本换到别的文件就不放行：白名单按文件名写死。
    with pytest.raises(MigrationError, match="没有在同一文件重建"):
        assert_migration_sql(_VIEW_SWAP, filename="0021_other.sql")


@pytest.mark.unit
def test_view_swap_requires_the_same_name_directly_after_drop() -> None:
    other_view = _VIEW_SWAP.replace(
        'CREATE VIEW src_wind."AINDEXINDUSTRIESCITICS"', 'CREATE VIEW src_wind."OTHER"'
    )
    with pytest.raises(MigrationError, match="未紧跟同名 CREATE VIEW"):
        assert_migration_sql(other_view, filename="0020_aindexdescription.sql")
    with_gap = _VIEW_SWAP.replace(
        "CREATE VIEW",
        'CREATE INDEX "x" ON src_wind.y (_batch_id);\nCREATE VIEW',
    )
    with pytest.raises(MigrationError, match="未紧跟同名 CREATE VIEW"):
        assert_migration_sql(with_gap, filename="0020_aindexdescription.sql")
    other_table = _VIEW_SWAP.replace(
        'DROP TABLE src_wind."AINDEXINDUSTRIESCITICS"', 'DROP TABLE src_wind."AINDEXEODPRICES"'
    )
    with pytest.raises(MigrationError, match="白名单"):
        assert_migration_sql(other_table, filename="0020_aindexdescription.sql")


@pytest.mark.unit
def test_view_only_statement_is_not_dml() -> None:
    with pytest.raises(MigrationError, match="语句动词非法"):
        assert_migration_sql("UPDATE src_wind.x SET a = 1", filename="0020_aindexdescription.sql")


@pytest.mark.unit
def test_macro_drop_exemption_only_for_0018_leading_drops() -> None:
    assert_migration_sql(_MACRO_DROPS, filename="0018_macro_source_tables.sql")
    with pytest.raises(MigrationError, match="没有在同一文件重建"):
        assert_migration_sql(_MACRO_DROPS, filename="0019_other.sql")
    late = 'CREATE TABLE src_macro."gpr_daily" (id integer PRIMARY KEY);\n' + _MACRO_DROPS
    with pytest.raises(MigrationError, match="没有在同一文件重建"):
        assert_migration_sql(late, filename="0018_macro_source_tables.sql")
    partial = (
        'DROP TABLE src_macro."macro_gpr_daily";\n'
        'CREATE TABLE src_macro."gpr_daily" (id integer PRIMARY KEY);'
    )
    with pytest.raises(MigrationError, match="开头删表与白名单不一致"):
        assert_migration_sql(partial, filename="0018_macro_source_tables.sql")


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
        "0018_macro_source_tables.sql",
        "0019_bond_fx_wind_tables.sql",
        "0020_aindexdescription.sql",
        "0021_column_comments.sql",
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
def test_comment_is_allowed_only_on_column() -> None:
    assert_migration_sql(
        'COMMENT ON COLUMN src_wind."ASHAREINCOME"."TOT_OPER_REV" IS \'营业总收入\'',
        filename="0021_column_comments.sql",
    )
    with pytest.raises(MigrationError, match="只允许 COMMENT ON COLUMN"):
        assert_migration_sql(
            "COMMENT ON TABLE src_wind.\"ASHAREINCOME\" IS 'x'",
            filename="0021_column_comments.sql",
        )
    with pytest.raises(MigrationError, match="只允许 COMMENT ON COLUMN"):
        assert_migration_sql(
            "COMMENT ON COLUMN src_wind.\"ASHAREINCOME\".\"X\" IS 'a' || 'b'",
            filename="0021_column_comments.sql",
        )


@pytest.mark.unit
def test_split_keeps_semicolon_and_double_quote_inside_string_literal() -> None:
    sql = (
        'COMMENT ON COLUMN src_wind."T"."A" IS \'0 新增; 1 修改 "x"\';\n'
        "COMMENT ON COLUMN src_wind.\"T\".\"B\" IS 'it''s; ok';\n"
    )
    statements = split_sql_statements(sql)
    assert statements == (
        'COMMENT ON COLUMN src_wind."T"."A" IS \'0 新增; 1 修改 "x"\'',
        "COMMENT ON COLUMN src_wind.\"T\".\"B\" IS 'it''s; ok'",
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
