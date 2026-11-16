"""Dagster 运行表迁移与实例配置：只 CREATE，不自建。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from orchestration.dagster_storage import dagster_ops_migration_sql, dagster_ops_statements

from quantagent.adapters.postgres.migrate import split_sql_statements

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_dagster_storage_migration_matches_installed_metadata(repo_root: Path) -> None:
    path = repo_root / "db" / "migrations" / "ops" / "0002_dagster_storage.sql"
    assert path.read_text(encoding="utf-8") == dagster_ops_migration_sql()
    statements = split_sql_statements(path.read_text(encoding="utf-8"))
    assert statements == dagster_ops_statements()
    joined = "\n".join(statements)
    for name in ("ops.runs", "ops.event_logs", "ops.jobs", "ops.snapshots"):
        assert f"CREATE TABLE {name} " in joined
    assert "public." not in joined
    assert "ON DELETE CASCADE" in joined


@pytest.mark.unit
def test_dagster_instance_template_disables_autocreate(repo_root: Path) -> None:
    text = (repo_root / "orchestration" / "dagster.yaml").read_text(encoding="utf-8")
    assert "should_autocreate_tables: false" in text
    assert "telemetry:" in text
    assert "enabled: false" in text
    assert "-csearch_path=ops" in text
    assert "QUANTAGENT_PG_OPS_PASSWORD" in text
    assert "postgres://" not in text
