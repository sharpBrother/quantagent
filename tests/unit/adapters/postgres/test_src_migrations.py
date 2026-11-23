"""第一批 src_* 迁移 SQL 与清单一致。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from quantagent.adapters.postgres.migrate import list_migration_files, split_sql_statements
from quantagent.adapters.postgres.src_catalog import load_src_tables

if TYPE_CHECKING:
    from pathlib import Path


# 0020 把物理表 AINDEXINDUSTRIESCITICS 改成同名视图。清单里仍保留这一项，但它的终态是视图。
_VIEW_TABLES = frozenset({"AINDEXINDUSTRIESCITICS"})


@pytest.mark.unit
def test_keep_list_tables_are_created(repo_root: Path) -> None:
    tables = load_src_tables(repo_root)
    assert len(tables) == 63
    sql = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((repo_root / "db" / "migrations" / "src").glob("*.sql"))
    )
    for table in tables:
        kind = "VIEW" if table.name in _VIEW_TABLES else "TABLE"
        needle = f'CREATE {kind} {table.schema}."{table.name}"'
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
    # 视图没有存储，不需要 _batch_id 索引。0020 之后的终态里，它不在这个集合中。
    with_batch -= _view_names(statements)
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
    # 63 张清单表减去 0020 改成视图的 AINDEXINDUSTRIESCITICS，加上 0008 建的 ASHARECALENDAR（不在清单）
    # 与 0007 建后被 0018 删除的三张旧宏观表。0007 已应用不能改，所以旧表的 CREATE 仍在迁移文件里。
    assert len(with_batch) == 66
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


# 0018 按分表原则删三张空的旧宏观表，不重建同名表。只放行文件开头这三条 DROP，
# 顺序与文件一致；其余语句仍必须是 CREATE。
_HISTORICAL_DROP_ONLY = {
    "0018_macro_source_tables.sql": (
        'src_macro."macro_jin10_usa_ism_pmi"',
        'src_macro."macro_gpr_daily"',
        'src_macro."macro_fred_observation"',
    ),
}


# 0019 删表重建六张债券曲线、回购与外汇表（0 行）。每条 DROP 紧跟同名 CREATE，
# 表集合与 migrate.py 的 _REBUILD_PAIRS 一致。
_BOND_FX_REBUILD = (
    'src_wind."CBONDCURVECNBD"',
    'src_wind."CBONDCURVECSI"',
    'src_wind."CBONDREPOANDIBLEODPRICES"',
    'src_wind."CBONDPRICESREPO"',
    'src_wind."CBONDREPO"',
    'src_wind."FXEODPRICES"',
)
_PAIR_REBUILD = {"0019_bond_fx_wind_tables.sql": _BOND_FX_REBUILD}

# 0020 删掉 0003 的空物理表 AINDEXINDUSTRIESCITICS，并在同文件建同名视图。每条 DROP 紧跟同名 CREATE VIEW。
_DROP_TO_VIEW = {
    "0020_aindexdescription.sql": ('src_wind."AINDEXINDUSTRIESCITICS"',),
}


def _view_names(statements: list[str] | tuple[str, ...]) -> set[str]:
    return {
        match.group(1)
        for stmt in statements
        if (match := re.match(r"CREATE VIEW (src_\w+\.\"[^\"]+\")\s+AS\b", stmt)) is not None
    }


@pytest.mark.unit
def test_src_sql_has_no_drop_or_dml(repo_root: Path) -> None:
    files = list_migration_files(repo_root, "src")
    statements: list[str] = []
    for item in files:
        file_statements = split_sql_statements(item.path.read_text(encoding="utf-8"))
        pair_names = _PAIR_REBUILD.get(item.path.name)
        if pair_names is not None:
            drops = [s for s in file_statements if s.startswith("DROP TABLE")]
            assert drops == [f"DROP TABLE {name}" for name in pair_names], item.path.name
            for pos, stmt in enumerate(file_statements):
                if stmt.startswith("DROP TABLE"):
                    name = stmt.removeprefix("DROP TABLE ")
                    assert file_statements[pos + 1].startswith(f"CREATE TABLE {name} ("), name
            file_statements = tuple(s for s in file_statements if not s.startswith("DROP TABLE"))
        view_names = _DROP_TO_VIEW.get(item.path.name)
        if view_names is not None:
            drops = [s for s in file_statements if s.startswith("DROP TABLE")]
            assert drops == [f"DROP TABLE {name}" for name in view_names], item.path.name
            for pos, stmt in enumerate(file_statements):
                if stmt.startswith("DROP TABLE"):
                    name = stmt.removeprefix("DROP TABLE ")
                    assert file_statements[pos + 1].startswith(f"CREATE VIEW {name} AS"), name
            file_statements = tuple(s for s in file_statements if not s.startswith("DROP TABLE"))
        rebuilt = _HISTORICAL_DROP_REBUILD.get(item.path.name)
        if rebuilt is not None:
            assert file_statements[0] == f"DROP TABLE {rebuilt}", item.path.name
            assert file_statements[1].startswith(f"CREATE TABLE {rebuilt} ("), item.path.name
            file_statements = file_statements[1:]
        drop_only = _HISTORICAL_DROP_ONLY.get(item.path.name)
        if drop_only is not None:
            head = file_statements[: len(drop_only)]
            assert list(head) == [f"DROP TABLE {name}" for name in drop_only], item.path.name
            file_statements = file_statements[len(drop_only) :]
        statements.extend(file_statements)
    assert statements
    # 列注释是唯一允许的非 CREATE 语句；迁移运行器只放行 COMMENT ON COLUMN 的完整形式。
    assert all(
        stmt.split(None, 1)[0].upper() == "CREATE" or stmt.startswith("COMMENT ON COLUMN ")
        for stmt in statements
    )


@pytest.mark.unit
def test_ops_sql_creates_schema_only(repo_root: Path) -> None:
    text = (repo_root / "db" / "migrations" / "ops" / "0001_schema.sql").read_text(encoding="utf-8")
    assert "CREATE SCHEMA ops;" in text
    assert "CREATE TABLE" not in text


@pytest.mark.unit
def test_batch_id_index_follows_last_table_rebuild(repo_root: Path) -> None:
    # 删表重建会连带删掉索引：每张表最后一次 CREATE TABLE 之后必须再有 _batch_id 索引。
    files = list_migration_files(repo_root, "src")
    statements: list[str] = []
    for item in files:
        statements.extend(split_sql_statements(item.path.read_text(encoding="utf-8")))
    last_create: dict[str, int] = {}
    last_index: dict[str, int] = {}
    for pos, stmt in enumerate(statements):
        created = re.match(r"CREATE TABLE (src_\w+\.\"[^\"]+\")", stmt)
        if created is not None and "_batch_id bigint NOT NULL REFERENCES" in stmt:
            last_create[created.group(1)] = pos
        indexed = re.match(r"CREATE INDEX \"[^\"]+\" ON (src_\w+\.\"[^\"]+\") \(_batch_id\)$", stmt)
        if indexed is not None:
            last_index[indexed.group(1)] = pos
    # 被视图取代的表已不存在，不需要索引。
    for view in _view_names(statements):
        last_create.pop(view, None)
    missing = sorted(t for t, pos in last_create.items() if last_index.get(t, -1) < pos)
    assert missing == []
