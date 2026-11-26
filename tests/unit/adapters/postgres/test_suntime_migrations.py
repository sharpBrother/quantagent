"""朝阳永续 P0/P1 规格与迁移 DDL 一致，分页游标有索引。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from quantagent.adapters.postgres.migrate import list_migration_files, split_sql_statements
from quantagent.adapters.postgres.src_targets import SUNTIME_SPECS

if TYPE_CHECKING:
    from pathlib import Path

_TECH = {"_batch_id", "_ingested_at", "_row_hash"}


def _last_columns(repo_root: Path) -> dict[str, list[str]]:
    tables: dict[str, list[str]] = {}
    for item in list_migration_files(repo_root, "src"):
        for stmt in split_sql_statements(item.path.read_text(encoding="utf-8")):
            match = re.match(r'CREATE TABLE src_suntime\."(\w+)" \((.*)\)$', stmt, re.S)
            if match is None:
                continue
            cols = re.findall(r'^\s*"(\w+)"\s+\w', match.group(2), re.M)
            tables[match.group(1)] = cols
    return tables


@pytest.mark.unit
def test_suntime_specs_match_last_ddl(repo_root: Path) -> None:
    ddl = _last_columns(repo_root)
    for name, spec in SUNTIME_SPECS.items():
        expected = [column for column in ddl[name] if column not in _TECH]
        assert list(spec.native_columns) == expected, name
        assert spec.dataset == f"src.suntime.{name}", name
        assert spec.keys == ("id",)
        assert spec.system_columns == ("entrytime", "updatetime", "tmstamp"), name


@pytest.mark.unit
def test_con_forecast_stk_ttm_is_not_writable() -> None:
    # 旧仓派生表：0006 留着空表，不进写入白名单，采集不得写它。
    assert "con_forecast_stk_ttm" not in SUNTIME_SPECS


@pytest.mark.unit
def test_every_suntime_paged_table_has_tmstamp_id_index(repo_root: Path) -> None:
    statements: list[str] = []
    for item in list_migration_files(repo_root, "src"):
        statements.extend(split_sql_statements(item.path.read_text(encoding="utf-8")))
    for name in SUNTIME_SPECS:
        assert (
            f'CREATE INDEX "{name}__tmstamp_id_idx" ON src_suntime."{name}" ("tmstamp", "id")'
            in statements
        ), name
