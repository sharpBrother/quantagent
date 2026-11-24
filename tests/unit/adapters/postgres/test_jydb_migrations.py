"""JYDB P0/P1 规格与迁移 DDL 一致，分页游标有索引。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from quantagent.adapters.postgres.migrate import list_migration_files, split_sql_statements
from quantagent.adapters.postgres.src_targets import JYDB_SPECS

if TYPE_CHECKING:
    from pathlib import Path

_TECH = {"_batch_id", "_ingested_at", "_row_hash"}


def _last_columns(repo_root: Path) -> dict[str, list[str]]:
    tables: dict[str, list[str]] = {}
    for item in list_migration_files(repo_root, "src"):
        for stmt in split_sql_statements(item.path.read_text(encoding="utf-8")):
            match = re.match(r'CREATE TABLE src_jydb\."(\w+)" \((.*)\)$', stmt, re.S)
            if match is None:
                continue
            cols = re.findall(r'^\s*"(\w+)"\s+\w', match.group(2), re.M)
            tables[match.group(1)] = cols
    return tables


@pytest.mark.unit
def test_jydb_specs_match_last_ddl(repo_root: Path) -> None:
    ddl = _last_columns(repo_root)
    for name, spec in JYDB_SPECS.items():
        expected = [column for column in ddl[name] if column not in _TECH]
        assert list(spec.native_columns) == expected, name
        assert spec.dataset == f"src.jydb.{name.lower()}", name
        assert spec.keys == ("ID",)


@pytest.mark.unit
def test_c_in_indicatormain_has_pk_and_cursor_index(repo_root: Path) -> None:
    statements: list[str] = []
    for item in list_migration_files(repo_root, "src"):
        statements.extend(split_sql_statements(item.path.read_text(encoding="utf-8")))
    create = next(
        stmt
        for stmt in statements
        if stmt.startswith('CREATE TABLE src_jydb."C_IN_IndicatorMain"')
    )
    assert 'PRIMARY KEY ("ID")' in create
    assert (
        'CREATE INDEX "C_IN_IndicatorMain__batch_id_idx" '
        'ON src_jydb."C_IN_IndicatorMain" (_batch_id)'
    ) in statements


@pytest.mark.unit
def test_every_jydb_paged_table_has_jsid_id_index(repo_root: Path) -> None:
    statements: list[str] = []
    for item in list_migration_files(repo_root, "src"):
        statements.extend(split_sql_statements(item.path.read_text(encoding="utf-8")))
    for name in JYDB_SPECS:
        assert (
            f'CREATE INDEX "{name}__jsid_id_idx" ON src_jydb."{name}" ("JSID", "ID")'
            in statements
        ), name


@pytest.mark.unit
def test_qt_osindexquote_rebuild_has_pk_and_read_index(repo_root: Path) -> None:
    statements: list[str] = []
    for item in list_migration_files(repo_root, "src"):
        statements.extend(split_sql_statements(item.path.read_text(encoding="utf-8")))
    create = next(
        stmt
        for stmt in reversed(statements)
        if stmt.startswith('CREATE TABLE src_jydb."QT_OSIndexQuote"')
    )
    assert 'PRIMARY KEY ("ID")' in create
    assert (
        'CREATE INDEX "QT_OSIndexQuote__IndexCode_TradingDay_idx" '
        'ON src_jydb."QT_OSIndexQuote" ("IndexCode", "TradingDay")'
    ) in statements
