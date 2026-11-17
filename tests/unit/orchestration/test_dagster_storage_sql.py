"""Dagster 运行表迁移与实例配置：只 CREATE，不自建。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
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
def test_dagster_instance_template_uses_local_storage(repo_root: Path) -> None:
    # 执行机经 ToDesk 连 PG，daemon 的常驻连接会被吞掉；运行存储必须是本地 SQLite。
    data = yaml.safe_load(
        (repo_root / "orchestration" / "dagster.yaml").read_text(encoding="utf-8")
    )
    assert "storage" not in data
    assert "run_storage" not in data
    assert data["run_coordinator"]["class"] == "QueuedRunCoordinator"
    assert data["run_coordinator"]["config"]["max_concurrent_runs"] == 1
