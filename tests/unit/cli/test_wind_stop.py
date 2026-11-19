"""初始化作业按 run ID 请求安全停止。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from dagster import DagsterInstance, DagsterRunStatus
from typer.testing import CliRunner

from quantagent.cli.app import app
from quantagent.ingest.jobs.wind_control import wind_stop_path
from quantagent.platform.config import Settings
from quantagent.platform.storage.paths import resolve_var_paths

if TYPE_CHECKING:
    from pathlib import Path

RUN_ID = "b0e4bc1a-df9f-4df4-a78b-26d378837f03"
OTHER_ID = "b0e4bc1a-df9f-4df4-a78b-26d378837f04"


@pytest.mark.unit
def test_stop_command_targets_only_active_initial_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(_env_file=None, var_root=tmp_path / "var")
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    monkeypatch.setattr("quantagent.cli.ingest.get_settings", lambda: settings)
    monkeypatch.setattr("quantagent.cli.ingest.detect_repo_root", lambda: tmp_path)
    run = SimpleNamespace(job_name="wind_initial_backfill", status=DagsterRunStatus.STARTED)
    monkeypatch.setattr(
        DagsterInstance, "get", lambda: SimpleNamespace(get_run_by_id=lambda _: run)
    )
    ready = wind_stop_path(paths, RUN_ID).with_suffix(".ready")
    ready.parent.mkdir(parents=True)
    ready.touch()
    result = CliRunner().invoke(app, ["ingest", "wind", "stop-after-page", "--run-id", RUN_ID])
    assert result.exit_code == 0, result.output
    assert wind_stop_path(paths, RUN_ID).exists()
    assert not wind_stop_path(paths, OTHER_ID).exists()


@pytest.mark.unit
@pytest.mark.parametrize(
    "job_name,status",
    [
        ("wind_source_daily", DagsterRunStatus.STARTED),
        ("wind_initial_backfill", DagsterRunStatus.SUCCESS),
    ],
)
def test_stop_command_rejects_wrong_or_finished_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, job_name: str, status: DagsterRunStatus
) -> None:
    settings = Settings(_env_file=None, var_root=tmp_path / "var")
    monkeypatch.setattr("quantagent.cli.ingest.get_settings", lambda: settings)
    monkeypatch.setattr("quantagent.cli.ingest.detect_repo_root", lambda: tmp_path)
    run = SimpleNamespace(job_name=job_name, status=status)
    monkeypatch.setattr(
        DagsterInstance, "get", lambda: SimpleNamespace(get_run_by_id=lambda _: run)
    )
    result = CliRunner().invoke(app, ["ingest", "wind", "stop-after-page", "--run-id", RUN_ID])
    assert result.exit_code != 0
    assert not (tmp_path / "var").exists()


@pytest.mark.unit
def test_stop_command_rejects_running_old_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(_env_file=None, var_root=tmp_path / "var")
    monkeypatch.setattr("quantagent.cli.ingest.get_settings", lambda: settings)
    monkeypatch.setattr("quantagent.cli.ingest.detect_repo_root", lambda: tmp_path)
    run = SimpleNamespace(job_name="wind_initial_backfill", status=DagsterRunStatus.STARTED)
    monkeypatch.setattr(
        DagsterInstance, "get", lambda: SimpleNamespace(get_run_by_id=lambda _: run)
    )
    result = CliRunner().invoke(app, ["ingest", "wind", "stop-after-page", "--run-id", RUN_ID])
    assert result.exit_code != 0
    assert "旧代码" in result.output
    assert not (tmp_path / "var").exists()


@pytest.mark.unit
def test_stop_command_rejects_invalid_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(_env_file=None, var_root=tmp_path / "var")
    monkeypatch.setattr("quantagent.cli.ingest.get_settings", lambda: settings)
    monkeypatch.setattr("quantagent.cli.ingest.detect_repo_root", lambda: tmp_path)
    result = CliRunner().invoke(app, ["ingest", "wind", "stop-after-page", "--run-id", "../escape"])
    assert result.exit_code != 0
    assert not (tmp_path / "var").exists()
