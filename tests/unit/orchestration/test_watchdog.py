"""共享看门狗 run_watched_child：停滞终止、SIGTERM 不生效时升级 SIGKILL、正常返回。

替身子进程只用模块顶层函数；不连接任何数据库或源库。
"""

from __future__ import annotations

import json
import signal
import time
from typing import TYPE_CHECKING

import pytest
from orchestration.resources.watchdog import PageProgress, run_watched_child

from quantagent.ingest.errors import IngestStalledError

if TYPE_CHECKING:
    from collections.abc import Callable
    from multiprocessing.connection import Connection
    from pathlib import Path


def _hang_honoring_term(*, progress_path: Path, conn: Connection, **_: object) -> None:
    # 默认的 SIGTERM 处理会直接结束子进程。
    PageProgress(progress_path).mark_phase("source_fetch", 1)
    time.sleep(3600)


def _hang_ignoring_term(*, progress_path: Path, conn: Connection, **_: object) -> None:
    # 模拟 ADR 中“SIGTERM 不能让它退出”的情况。
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    PageProgress(progress_path).mark_phase("source_fetch", 1)
    time.sleep(3600)


def _ok(*, progress_path: Path, conn: Connection, **_: object) -> None:
    progress = PageProgress(progress_path)
    progress(1)
    progress(2)
    conn.send(("ok", {"pages": 2}))
    conn.close()


def _run(tmp_path: Path, target: Callable[..., None], *, stall_seconds: float) -> object:
    return run_watched_child(
        table="QT_OSINDEXQUOTE",
        progress_dir=tmp_path / "progress",
        child_target=target,
        child_kwargs={},
        stall_seconds=stall_seconds,
        poll_seconds=0.1,
        term_grace_seconds=0.5,
    )


def _failure_record(progress_dir: Path) -> dict[str, object]:
    failure = next(progress_dir.glob("*.failure.json"))
    record: dict[str, object] = json.loads(failure.read_text(encoding="utf-8"))
    return record


@pytest.mark.unit
def test_stalled_child_is_terminated_with_sigterm_first(tmp_path: Path) -> None:
    started = time.monotonic()
    with pytest.raises(IngestStalledError, match=r"QT_OSINDEXQUOTE.*source_fetch"):
        _run(tmp_path, _hang_honoring_term, stall_seconds=1)
    assert time.monotonic() - started < 20
    record = _failure_record(tmp_path / "progress")
    # exitcode -15 表示子进程收到并响应了 SIGTERM，没有进入 SIGKILL 升级。
    assert record["exitcode"] == -signal.SIGTERM


@pytest.mark.unit
def test_child_ignoring_sigterm_is_escalated_to_sigkill(tmp_path: Path) -> None:
    started = time.monotonic()
    with pytest.raises(IngestStalledError, match="须核实事务状态"):
        _run(tmp_path, _hang_ignoring_term, stall_seconds=1)
    assert time.monotonic() - started < 20
    record = _failure_record(tmp_path / "progress")
    # exitcode -9 表示宽限期过后由 SIGKILL 结束。
    assert record["exitcode"] == -signal.SIGKILL


@pytest.mark.unit
def test_normal_completion_returns_payload_and_cleans_up(tmp_path: Path) -> None:
    result = _run(tmp_path, _ok, stall_seconds=30)
    assert result == {"pages": 2}
    assert list((tmp_path / "progress").iterdir()) == []
