"""Wind 采集子进程看门狗：无进展终止、正常返回、子进程报错三条路径。

子进程目标函数必须是模块顶层函数，spawn 才能按名字导入。这里不连接数据库。
"""

from __future__ import annotations

import multiprocessing
import os
import time
from typing import TYPE_CHECKING

import pytest
from orchestration.resources.wind import WindIngestResource

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
    # 模拟被吞掉的连接：永远不写进度，也不返回。
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
def test_stalled_child_is_killed_and_raises(tmp_path: Path) -> None:
    resource, paths = _resource(tmp_path, stall_seconds=1)
    started = time.monotonic()
    with pytest.raises(IngestStalledError, match="没有新页提交"):
        resource._run_watched(
            "ASHAREEODPRICES",
            write_db=False,
            page_size=10,
            max_pages=1,
            child_target=_hang_forever,
            poll_seconds=0.2,
        )
    assert time.monotonic() - started < 20
    assert multiprocessing.active_children() == []
    progress_path = _progress_dir(paths) / f"ASHAREEODPRICES.{os.getpid()}.progress"
    assert not progress_path.exists()


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
    assert list(_progress_dir(paths).iterdir()) == []
