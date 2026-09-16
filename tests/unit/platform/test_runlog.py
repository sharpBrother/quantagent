"""run log 落盘且拒绝覆盖。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from quantagent.platform.config import Settings
from quantagent.platform.errors import RunLogError
from quantagent.platform.runlog import RunLog, persist_run_log
from quantagent.platform.storage import resolve_var_paths

if TYPE_CHECKING:
    from pathlib import Path

    from quantagent.platform.storage.paths import VarPaths


def _paths(tmp_path: Path) -> VarPaths:
    settings = Settings(_env_file=None, var_root=tmp_path / "var")
    return resolve_var_paths(settings, repo_root=tmp_path)


@pytest.mark.unit
def test_persist_run_log_writes_json(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    record = RunLog(
        action="check.contracts",
        status="success",
        finished_at=datetime.now(UTC),
        input_digest="a" * 64,
        output_digest="b" * 64,
        row_count=0,
        dml_count=0,
    )
    dest = persist_run_log(record, paths)
    assert dest.is_file()
    assert dest.parent == paths.runs
    text = dest.read_text(encoding="utf-8")
    assert record.run_id in text
    assert "check.contracts" in text


@pytest.mark.unit
def test_persist_run_log_refuses_overwrite(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    record = RunLog(
        run_id="abc123",
        action="once",
        status="success",
        finished_at=datetime.now(UTC),
    )
    persist_run_log(record, paths)
    with pytest.raises(RunLogError, match="拒绝覆盖"):
        persist_run_log(record, paths)


@pytest.mark.unit
def test_failure_run_log_requires_error() -> None:
    with pytest.raises(ValueError, match="error"):
        RunLog(action="x", status="failure", finished_at=datetime.now(UTC))
