"""第一批其余常规 Wind 表的接入：写入白名单、分页白名单、采集列与 DDL 一致。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from quantagent.adapters.postgres.migrate import list_migration_files, split_sql_statements
from quantagent.adapters.postgres.src_targets import FIRST_BATCH_WIND_SPECS
from quantagent.adapters.postgres.wind_first_batch_columns import FIRST_BATCH_WIND_SYNC
from quantagent.ingest.sources.wind.tables import resolve_wind_paged_table
from quantagent.ingest.writers.tables import assert_writable

if TYPE_CHECKING:
    from pathlib import Path

_TECH = {"_batch_id", "_ingested_at", "_row_hash", "GSUPDTIME"}


def _ddl_columns(repo_root: Path) -> dict[str, list[str]]:
    tables: dict[str, list[str]] = {}
    for item in list_migration_files(repo_root, "src"):
        for stmt in split_sql_statements(item.path.read_text(encoding="utf-8")):
            match = re.match(r'CREATE TABLE src_wind\."(\w+)" \((.*)\)$', stmt, re.S)
            if match is None:
                continue
            cols = re.findall(r'^\s*"?(\w+)"?\s+\w', match.group(2), re.M)
            tables[match.group(1)] = [c for c in cols if c != "PRIMARY"]
    return tables


@pytest.mark.unit
def test_first_batch_tables_are_writable_and_paged() -> None:
    assert len(FIRST_BATCH_WIND_SYNC) == 15
    assert FIRST_BATCH_WIND_SYNC[0] == "ASHAREDESCRIPTION"
    for name in FIRST_BATCH_WIND_SYNC:
        spec = FIRST_BATCH_WIND_SPECS[name]
        assert spec.dataset == f"src.wind.{name.lower()}"
        assert spec.keys == ("OBJECT_ID",)
        assert {"OBJECT_ID", "OPDATE", "OPMODE"} <= set(spec.native_columns)
        assert "GSUPDTIME" not in spec.native_columns
        assert_writable(spec)
        paged = resolve_wind_paged_table(name)
        assert paged.spec == spec
        assert paged.source_table == name


@pytest.mark.unit
def test_first_batch_columns_match_applied_ddl(repo_root: Path) -> None:
    ddl = _ddl_columns(repo_root)
    for name in FIRST_BATCH_WIND_SYNC:
        expected = [c for c in ddl[name] if c not in _TECH]
        assert list(FIRST_BATCH_WIND_SPECS[name].native_columns) == expected, name


@pytest.mark.unit
def test_first_batch_chi_fields_follow_legacy() -> None:
    assert resolve_wind_paged_table("ASHAREDESCRIPTION").chi_fields == (
        "S_INFO_NAME",
        "S_INFO_COMPNAME",
        "S_INFO_LISTBOARDNAME",
    )
    assert resolve_wind_paged_table("ASHAREDIVIDEND").chi_fields == ("S_DIV_OBJECT",)
    assert resolve_wind_paged_table("AINDEXMEMBERS").chi_fields == ()
