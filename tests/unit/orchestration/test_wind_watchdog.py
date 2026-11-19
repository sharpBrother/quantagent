"""Wind 采集子进程看门狗：无进展终止、正常返回、子进程报错三条路径。

子进程目标函数必须是模块顶层函数，spawn 才能按名字导入。这里不连接数据库。
"""

from __future__ import annotations

import json
import multiprocessing
import os
import time
from typing import TYPE_CHECKING

import pytest
from orchestration.resources.wind import WindIngestResource, _last_progress_time, _PageProgress

from quantagent.ingest.errors import IngestError, IngestStalledError
from quantagent.platform.config import Settings
from quantagent.platform.storage.paths import resolve_var_paths

if TYPE_CHECKING:
    from multiprocessing.connection import Connection
    from pathlib import Path

    from quantagent.platform.storage.paths import VarPaths


def _hang_forever(
    *,
    settings: Settings,
    paths: VarPaths,
    table: str,
    write_db: bool,
    page_size: int,
    max_pages: int | None,
    progress_path: Path,
    conn: Connection,
) -> None:
    # 阶段更新不应掩盖长时间没有新页提交。
    _PageProgress(progress_path).mark_phase("source_fetch", 1)
    time.sleep(3600)


def _ok_with_progress(
    *,
    settings: Settings,
    paths: VarPaths,
    table: str,
    write_db: bool,
    page_size: int,
    max_pages: int | None,
    progress_path: Path,
    conn: Connection,
) -> None:
    for pages in (1, 2, 3):
        progress_path.write_text(str(pages), encoding="utf-8")
        time.sleep(0.1)
    conn.send(("ok", {"pages": 3, "table": table}))
    conn.close()


def _child_error(
    *,
    settings: Settings,
    paths: VarPaths,
    table: str,
    write_db: bool,
    page_size: int,
    max_pages: int | None,
    progress_path: Path,
    conn: Connection,
) -> None:
    progress = _PageProgress(progress_path)
    progress(2)
    progress.mark_phase("pg_write_and_verify", 3, "cursor-2", "cursor-3")
    conn.send(("error", "X: boom"))
    conn.close()


def _resource(tmp_path: Path, *, stall_seconds: float) -> tuple[WindIngestResource, VarPaths]:
    settings = Settings(_env_file=None, var_root=tmp_path / "var", allow_db_write=False)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    resource = WindIngestResource(settings=settings, paths=paths, stall_seconds=stall_seconds)
    return resource, paths


def _progress_dir(paths: VarPaths) -> Path:
    return paths.logs / "wind_ingest_progress"


@pytest.mark.unit
def test_stage_does_not_refresh_commit_clock(tmp_path: Path) -> None:
    progress_path = tmp_path / "table.progress"
    progress = _PageProgress(progress_path)
    progress(3)
    before = _last_progress_time(progress_path, 0)
    progress.mark_phase("source_fetch", 4)
    assert _last_progress_time(progress_path, 0) == before
    assert '"phase": "source_fetch"' in progress.stage_path.read_text(encoding="utf-8")
    assert '"page": 4' in progress.stage_path.read_text(encoding="utf-8")


@pytest.mark.unit
def test_stalled_child_is_killed_and_raises(tmp_path: Path) -> None:
    resource, paths = _resource(tmp_path, stall_seconds=10)
    started = time.monotonic()
    with pytest.raises(IngestStalledError, match="source_fetch"):
        resource._run_watched(
            "ASHAREEODPRICES",
            write_db=False,
            page_size=10,
            max_pages=1,
            child_target=_hang_forever,
            poll_seconds=0.2,
        )
    assert time.monotonic() - started < 35
    assert multiprocessing.active_children() == []
    progress_path = _progress_dir(paths) / f"ASHAREEODPRICES.{os.getpid()}.progress"
    assert not progress_path.exists()
    assert not progress_path.with_suffix(".stage.json").exists()
    failure = next(_progress_dir(paths).glob("*.failure.json"))
    assert json.loads(json.loads(failure.read_text(encoding="utf-8"))["stage"])["phase"] == (
        "source_fetch"
    )


@pytest.mark.unit
def test_ok_result_is_returned(tmp_path: Path) -> None:
    resource, paths = _resource(tmp_path, stall_seconds=30)
    result: object = resource._run_watched(
        "ASHAREEODPRICES",
        write_db=False,
        page_size=10,
        max_pages=1,
        child_target=_ok_with_progress,
        poll_seconds=0.2,
    )
    assert result == {"pages": 3, "table": "ASHAREEODPRICES"}
    assert list(_progress_dir(paths).iterdir()) == []


@pytest.mark.unit
def test_child_error_is_raised_as_ingest_error(tmp_path: Path) -> None:
    resource, paths = _resource(tmp_path, stall_seconds=30)
    with pytest.raises(IngestError, match="boom"):
        resource._run_watched(
            "ASHAREEODPRICES",
            write_db=False,
            page_size=10,
            max_pages=1,
            child_target=_child_error,
            poll_seconds=0.2,
        )
    failure = next(_progress_dir(paths).glob("*.failure.json"))
    record = json.loads(failure.read_text(encoding="utf-8"))
    assert record["error_type"] == "IngestError"
    assert record["committed_pages"] == "2"
    stage = json.loads(record["stage"])
    assert stage["phase"] == "pg_write_and_verify"
    assert stage["start_cursor"] == "cursor-2"
    assert stage["end_cursor"] == "cursor-3"
