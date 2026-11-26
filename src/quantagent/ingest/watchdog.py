"""采集子进程看门狗。Wind、聚源、朝阳永续共用，CLI 与 Dagster 资产都从这里取。

放在 ingest 层而不是 orchestration：CLI（``quantagent ingest``）与 Dagster 资产
都需要看门狗保护，而 CLI 不能反向依赖 orchestration。``orchestration.resources.watchdog``
现在只是本模块的 re-export，保持既有 import 路径不破。

父进程在 spawn 出的子进程里跑采集，盯着“最近一次成功提交页”的时间。超过阈值没有新页，
就终止子进程并抛 ``IngestStalledError``。

为什么用子进程：执行机经 ToDesk 端口转发连 PG 和源库，转发会吞掉连接。被吞的连接上，
驱动调用永不返回，同一线程里无法中断，只能由别的进程终止它。
为什么按“无进展”而不是总时长：全量回填一张表可达数小时，总时长上限会误杀正常作业。
为什么 600 秒：沿用 docs/adr/2026-11-17-dagster-local-run-storage.md。单页读写通常是秒级，
十分钟没有新页才视为停滞。
终止时可能恰逢提交；父进程只记录阶段并报错，事务状态核实前不可重试。
"""

from __future__ import annotations

import json
import multiprocessing
import os
import time
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from multiprocessing.connection import Connection
    from multiprocessing.process import BaseProcess
    from pathlib import Path

# 沿用 ADR 2026-11-17 的 600 秒。
DEFAULT_STALL_SECONDS = 600.0
# SIGTERM 后的宽限期。spawn 出的子进程使用默认信号处理，SIGTERM 通常立即生效；
# 宽限期只为子进程忽略 SIGTERM 的情况留时间，到期即 SIGKILL。
TERM_GRACE_SECONDS = 10.0
POLL_SECONDS = 5.0


class PageProgress:
    """子进程侧的进度写入器。

    提交计数文件的 mtime 是看门狗时钟，只在页提交返回之后更新。阶段文件供诊断，
    不刷新时钟，否则慢查询的阶段更新会掩盖停滞。
    """

    def __init__(self, progress_path: Path) -> None:
        self.progress_path = progress_path
        self.stage_path = progress_path.with_suffix(".stage.json")

    def __call__(self, pages: int) -> None:
        self.progress_path.write_text(str(pages), encoding="utf-8")

    def mark_phase(
        self,
        phase: str,
        page: int,
        start_cursor: str | None = None,
        end_cursor: str | None = None,
    ) -> None:
        self.stage_path.write_text(
            json.dumps(
                {
                    "phase": phase,
                    "page": page,
                    "started_at": datetime.now(UTC).isoformat(),
                    "start_cursor": start_cursor,
                    "end_cursor": end_cursor,
                }
            ),
            encoding="utf-8",
        )


def last_progress_time(progress_path: Path, started_wall: float) -> float:
    # 子进程开始前还没有进度文件，计时从启动时刻算起，覆盖子进程导入慢或卡死在连接上的情况。
    try:
        return progress_path.stat().st_mtime
    except FileNotFoundError:
        return started_wall


def stop_child(proc: BaseProcess, grace_seconds: float) -> None:
    """先 SIGTERM，宽限期内未退出再 SIGKILL。SIGKILL 不可忽略，是最后手段。"""
    if proc.is_alive():
        proc.terminate()
    proc.join(grace_seconds)
    if proc.is_alive():
        proc.kill()
    proc.join(10)


def run_watched_child(
    *,
    table: str,
    progress_dir: Path,
    child_target: Callable[..., None],
    child_kwargs: Mapping[str, object],
    stall_seconds: float = DEFAULT_STALL_SECONDS,
    poll_seconds: float = POLL_SECONDS,
    term_grace_seconds: float = TERM_GRACE_SECONDS,
) -> object:
    """在子进程里跑 ``child_target``，返回它通过管道发回的 ``("ok", payload)`` 中的 payload。

    子进程必须用 ``progress_path`` 与 ``conn`` 两个关键字参数：每提交一页调用
    ``PageProgress``，结束时经 ``conn`` 发送 ``(kind, payload)``，kind 为 ``ok``、
    ``stopped`` 或 ``error``。``child_target`` 必须是模块顶层函数，spawn 才能按名字导入。
    """
    # 错误类在函数体内导入：本模块被 orchestration re-export，顶层导入会在 daemon 加载时提前拉起。
    from quantagent.ingest.errors import (  # noqa: PLC0415
        IngestError,
        IngestStalledError,
        IngestStoppedError,
    )

    progress_dir.mkdir(parents=True, exist_ok=True)
    progress_path = progress_dir / f"{table}.{os.getpid()}.progress"
    stage_path = progress_path.with_suffix(".stage.json")
    ctx = multiprocessing.get_context("spawn")
    recv_conn: Connection
    send_conn: Connection
    recv_conn, send_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=child_target,
        kwargs={**child_kwargs, "progress_path": progress_path, "conn": send_conn},
        name=f"ingest-{table}",
    )
    started_wall = time.time()
    try:
        proc.start()
        # 父进程关掉自己那份发送端，子进程退出后管道才会读到 EOF。
        send_conn.close()
        while True:
            proc.join(poll_seconds)
            if not proc.is_alive():
                break
            last = last_progress_time(progress_path, started_wall)
            if time.time() - last > stall_seconds:
                stop_child(proc, term_grace_seconds)
                try:
                    stage = stage_path.read_text(encoding="utf-8")
                except OSError:
                    stage = "未知"
                raise IngestStalledError(
                    f"{table} 超过 {stall_seconds:.0f} 秒没有新页提交，"
                    f"已终止子进程；须核实事务状态后再决定是否续跑；阶段={stage}"
                )
        try:
            kind, payload = recv_conn.recv()
        except EOFError:
            raise IngestError(f"采集子进程异常退出 exitcode={proc.exitcode}") from None
        if kind == "ok":
            return payload
        if kind == "stopped":
            raise IngestStoppedError(str(payload))
        raise IngestError(str(payload))
    except IngestStoppedError:
        raise
    except BaseException as exc:
        # 保留阶段与已提交页，供中断后核对事务；不能只依赖临时文件。
        with suppress(OSError):
            _save_failure(progress_path, stage_path, type(exc).__name__, proc.exitcode)
        raise
    finally:
        if proc.is_alive():
            stop_child(proc, term_grace_seconds)
        recv_conn.close()
        progress_path.unlink(missing_ok=True)
        stage_path.unlink(missing_ok=True)
        if not proc.is_alive():
            proc.close()


def _save_failure(
    progress_path: Path,
    stage_path: Path,
    error_type: str,
    exitcode: int | None,
) -> None:
    try:
        pages = progress_path.read_text(encoding="utf-8")
    except OSError:
        pages = None
    try:
        stage = stage_path.read_text(encoding="utf-8")
    except OSError:
        stage = None
    # exitcode 为负数时是信号编号：-9 表示 SIGKILL，-15 表示 SIGTERM。
    failure_path = progress_path.with_name(f"{progress_path.name}.{time.time_ns()}.failure.json")
    failure_path.write_text(
        json.dumps(
            {
                "error_type": error_type,
                "committed_pages": pages,
                "stage": stage,
                "exitcode": exitcode,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


__all__ = [
    "DEFAULT_STALL_SECONDS",
    "POLL_SECONDS",
    "TERM_GRACE_SECONDS",
    "PageProgress",
    "last_progress_time",
    "run_watched_child",
    "stop_child",
]
