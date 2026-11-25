"""聚源采集的注入点：在看门狗保护的子进程里跑 ``ingest_jydb_paged``。

执行机经 ToDesk 转发连聚源源库，连接被吞时 pymssql 调用永不返回。同一线程里无法中断，
因此和 Wind 一样由父进程按“无新页”超时终止子进程。不做停止标记：聚源日更没有按请求停止的需求。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from orchestration.resources.watchdog import (
    DEFAULT_STALL_SECONDS,
    POLL_SECONDS,
    TERM_GRACE_SECONDS,
    PageProgress,
    run_watched_child,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from multiprocessing.connection import Connection
    from pathlib import Path

    from quantagent.ingest.jobs.jydb_paged import JydbPagedIngestResult
    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths


class JydbIngestResource:
    def __init__(
        self,
        *,
        settings: Settings,
        paths: VarPaths,
        stall_seconds: float = DEFAULT_STALL_SECONDS,
    ) -> None:
        self._settings = settings
        self._paths = paths
        self._stall_seconds = stall_seconds

    def ingest(
        self,
        table: str,
        *,
        write_db: bool,
        page_size: int,
        max_pages: int | None,
    ) -> JydbPagedIngestResult:
        return self._run_watched(
            table,
            write_db=write_db,
            page_size=page_size,
            max_pages=max_pages,
        )

    def _run_watched(
        self,
        table: str,
        *,
        write_db: bool,
        page_size: int,
        max_pages: int | None,
        child_target: Callable[..., None] | None = None,
        poll_seconds: float = POLL_SECONDS,
        term_grace_seconds: float = TERM_GRACE_SECONDS,
    ) -> JydbPagedIngestResult:
        """``child_target`` 与轮询、宽限期参数仅供测试替换子进程函数和缩短等待时间。"""
        target = child_target if child_target is not None else _jydb_child
        child_kwargs: dict[str, object] = {
            "settings": self._settings,
            "paths": self._paths,
            "table": table,
            "write_db": write_db,
            "page_size": page_size,
            "max_pages": max_pages,
        }
        return cast(
            "JydbPagedIngestResult",
            run_watched_child(
                table=table,
                progress_dir=self._paths.logs / "jydb_ingest_progress",
                child_target=target,
                child_kwargs=child_kwargs,
                stall_seconds=self._stall_seconds,
                poll_seconds=poll_seconds,
                term_grace_seconds=term_grace_seconds,
            ),
        )


def _jydb_child(
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
    """子进程入口。必须是模块顶层函数，spawn 方式才能按名字导入它。"""
    from quantagent.ingest.jobs.jydb_paged import ingest_jydb_paged

    progress = PageProgress(progress_path)
    try:
        # 连接建立之前的停滞归为 initializing；进入页循环后由 ingest_jydb_paged 逐阶段标记。
        progress.mark_phase("initializing", 1)
        result = ingest_jydb_paged(
            settings=settings,
            paths=paths,
            table=table,
            write_db=write_db,
            page_size=page_size,
            max_pages=max_pages,
            on_page=progress,
        )
    except Exception as exc:
        conn.send(("error", f"{type(exc).__name__}: {exc}"))
    else:
        conn.send(("ok", result))
    finally:
        conn.close()
