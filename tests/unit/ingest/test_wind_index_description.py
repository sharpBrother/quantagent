"""指数基本资料两张表与 AINDEXINDUSTRIESCITICS 视图的 Wind 接入：规格、白名单与 0020 DDL 一致。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from quantagent.adapters.postgres.migrate import list_migration_files, split_sql_statements
from quantagent.adapters.postgres.src_targets import INDEX_DESCRIPTION_WIND_SPECS
from quantagent.adapters.postgres.wind_index_description_columns import (
    INDEX_DESCRIPTION_WIND_SYNC,
)
from quantagent.ingest.errors import TargetNotAllowedError
from quantagent.ingest.sources.wind.tables import WIND_PAGED_TABLES, resolve_wind_paged_table
from quantagent.ingest.writers.tables import ALLOWED_SRC_WRITE_TARGETS, assert_writable

if TYPE_CHECKING:
    from pathlib import Path

_TECH = frozenset({"_batch_id", "_ingested_at", "_row_hash"})
_CHI_FIELDS = (
    "S_INFO_NAME",
    "S_INFO_COMPNAME",
    "S_INFO_PUBLISHER",
    "S_INFO_INDEXSTYLE",
    "INDEX_INTRO",
    "INCOME_PROCESSING_METHOD",
    "WEIGHT_TYPE_NAME",
    "S_INFO_INDEXTYPE",
)


def _statements(repo_root: Path, filename: str) -> tuple[str, ...]:
    path = repo_root / "db" / "migrations" / "src" / filename
    return split_sql_statements(path.read_text(encoding="utf-8"))


def _find(statements: tuple[str, ...], prefix: str) -> str:
    matches = [s for s in statements if s.startswith(prefix)]
    assert len(matches) == 1, prefix
    return matches[0]


def _body_columns(stmt: str) -> list[str]:
    body = stmt[stmt.index("(") + 1 : stmt.rindex(")")]
    names = re.findall(r'^\s*"?(\w+)"?\s+\w', body, re.M)
    return [n for n in names if n not in _TECH and n != "PRIMARY"]


def _body_types(stmt: str) -> dict[str, str]:
    body = stmt[stmt.index("(") + 1 : stmt.rindex(")")]
    types: dict[str, str] = {}
    for name, rest in re.findall(r'^\s*"(\w+)"\s+(.+?)\s*,?$', body, re.M):
        types[name] = re.sub(r"\s+NOT NULL$", "", rest).strip()
    return types


@pytest.mark.unit
def test_sync_tuple_and_specs() -> None:
    assert INDEX_DESCRIPTION_WIND_SYNC == ("AINDEXDESCRIPTION", "AINDEXDESCRIPTIONZL")
    for name in INDEX_DESCRIPTION_WIND_SYNC:
        spec = INDEX_DESCRIPTION_WIND_SPECS[name]
        assert spec.dataset == f"src.wind.{name.lower()}"
        assert spec.pg_schema == "src_wind"
        assert spec.pg_table == name
        assert spec.keys == ("OBJECT_ID",)
        assert "GSUPDTIME" not in spec.native_columns
        assert ALLOWED_SRC_WRITE_TARGETS[spec.dataset] == spec
        assert_writable(spec, profile="office")
        with pytest.raises(TargetNotAllowedError, match="不负责写"):
            assert_writable(spec, profile="local")
        paged = resolve_wind_paged_table(name)
        assert paged.spec == spec
        assert paged.source_table == name
        assert paged.source_filter == ()
        assert paged.chi_fields == _CHI_FIELDS
        assert name in WIND_PAGED_TABLES


@pytest.mark.unit
def test_specs_match_0020_ddl(repo_root: Path) -> None:
    statements = _statements(repo_root, "0020_aindexdescription.sql")
    for name in INDEX_DESCRIPTION_WIND_SYNC:
        stmt = _find(statements, f'CREATE TABLE src_wind."{name}" (')
        assert list(INDEX_DESCRIPTION_WIND_SPECS[name].native_columns) == _body_columns(stmt), name
        assert '"OBJECT_ID" varchar(100) NOT NULL' in stmt, name
        assert 'PRIMARY KEY ("OBJECT_ID")' in stmt, name
        assert "GSUPDTIME" not in stmt, name
        # split_sql_statements 去掉了结尾分号，期望串也不带分号。
        assert f'CREATE INDEX "{name}__batch_id_idx" ON src_wind."{name}" (_batch_id)' in (
            statements
        ), name
        assert (
            f'CREATE INDEX "{name}__S_INFO_WINDCODE_idx" ON src_wind."{name}" ("S_INFO_WINDCODE")'
            in statements
        ), name


@pytest.mark.unit
def test_view_replaces_old_physical_table_with_same_columns(repo_root: Path) -> None:
    """视图列必须覆盖 0003 旧物理表的 26 个源列：名称、顺序、类型都一致，没有缺列。"""
    old = _find(
        _statements(repo_root, "0003_wind.sql"),
        'CREATE TABLE src_wind."AINDEXINDUSTRIESCITICS" (',
    )
    statements = _statements(repo_root, "0020_aindexdescription.sql")
    view = _find(statements, 'CREATE VIEW src_wind."AINDEXINDUSTRIESCITICS" AS')
    desc = _find(statements, 'CREATE TABLE src_wind."AINDEXDESCRIPTION" (')

    old_cols = _body_columns(old)
    assert len(old_cols) == 26
    # 只取 SELECT 与 FROM 之间的列表；视图名 src_wind."..." 里也含 d."，不能从整句解析。
    select_match = re.search(r"\bSELECT\b(.*?)\bFROM\b", view, re.S)
    assert select_match is not None
    view_cols = re.findall(r'\bd\."(\w+)"', select_match.group(1))
    assert view_cols == old_cols
    assert view_cols == _body_columns(desc)
    old_types = _body_types(old)
    desc_types = _body_types(desc)
    for name in old_cols:
        assert desc_types[name] == old_types[name], name


@pytest.mark.unit
def test_view_filters_on_citics_members_and_is_the_only_0020_view(repo_root: Path) -> None:
    statements = _statements(repo_root, "0020_aindexdescription.sql")
    view = _find(statements, 'CREATE VIEW src_wind."AINDEXINDUSTRIESCITICS" AS')
    assert 'FROM src_wind."AINDEXDESCRIPTION" d' in view
    assert 'WHERE d."S_INFO_WINDCODE" IN (' in view
    for source in (
        'src_wind."AINDEXMEMBERSCITICS"',
        'src_wind."AINDEXMEMBERSCITICS2"',
        'src_wind."AINDEXMEMBERSCITICS3"',
    ):
        assert f"FROM {source}" in view, source
    assert view.count("UNION") == 2
    # 0020 中 AINDEXINDUSTRIESCITICS 只以视图形式出现，不再有同名物理表的 CREATE。
    assert not [
        s for s in statements if s.startswith('CREATE TABLE src_wind."AINDEXINDUSTRIESCITICS"')
    ]


@pytest.mark.unit
def test_zl_table_is_not_referenced_by_any_view(repo_root: Path) -> None:
    views: list[str] = []
    for item in list_migration_files(repo_root, "src"):
        views.extend(
            s
            for s in split_sql_statements(item.path.read_text(encoding="utf-8"))
            if s.startswith("CREATE VIEW")
        )
    assert views
    assert all("AINDEXDESCRIPTIONZL" not in v for v in views)
