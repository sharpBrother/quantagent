"""朝阳永续采集的注入点：在看门狗保护的子进程里跑 ``ingest_suntime_paged``。

与聚源同一个理由：执行机经 ToDesk 转发连源库，连接被吞时 pymssql 调用永不返回，
同一线程里无法中断，只能由父进程按"无新页"超时终止子进程。
11-25 jydb 卡死 7 小时堵住单并发队列的事故说明：凡走这条链路的采集都不能没有看门狗。
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

    from quantagent.ingest.jobs.suntime_paged import SuntimePagedIngestResult
    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths


class SuntimeIngestResource:
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
        from_cursor: str | None = None,
    ) -> SuntimePagedIngestResult:
        return self._run_watched(
            table,
            write_db=write_db,
            page_size=page_size,
            max_pages=max_pages,
            from_cursor=from_cursor,
        )

    def _run_watched(
        self,
        table: str,
        *,
        write_db: bool,
        page_size: int,
        max_pages: int | None,
        from_cursor: str | None = None,
        child_target: Callable[..., None] | None = None,
        poll_seconds: float = POLL_SECONDS,
        term_grace_seconds: float = TERM_GRACE_SECONDS,
    ) -> SuntimePagedIngestResult:
        """``child_target`` 与轮询、宽限期参数仅供测试替换子进程函数和缩短等待时间。"""
        target = child_target if child_target is not None else _suntime_child
        child_kwargs: dict[str, object] = {
            "settings": self._settings,
            "paths": self._paths,
            "table": table,
            "write_db": write_db,
            "page_size": page_size,
            "max_pages": max_pages,
            "from_cursor": from_cursor,
        }
        return cast(
            "SuntimePagedIngestResult",
            run_watched_child(
                table=table,
                progress_dir=self._paths.logs / "suntime_ingest_progress",
                child_target=target,
                child_kwargs=child_kwargs,
                stall_seconds=self._stall_seconds,
                poll_seconds=poll_seconds,
                term_grace_seconds=term_grace_seconds,
            ),
        )


def _suntime_child(
    *,
    settings: Settings,
    paths: VarPaths,
    table: str,
    write_db: bool,
    page_size: int,
    max_pages: int | None,
    progress_path: Path,
    conn: Connection,
    from_cursor: str | None = None,
) -> None:
    """子进程入口。必须是模块顶层函数，spawn 方式才能按名字导入它。"""
    from quantagent.ingest.jobs.suntime_paged import ingest_suntime_paged

    progress = PageProgress(progress_path)
    try:
        # 连接建立之前的停滞归为 initializing；进入页循环后由 ingest_suntime_paged 逐阶段标记。
        progress.mark_phase("initializing", 1)
        result = ingest_suntime_paged(
            settings=settings,
            paths=paths,
            table=table,
            write_db=write_db,
            page_size=page_size,
            max_pages=max_pages,
            from_cursor=from_cursor,
            on_page=progress,
        )
    except Exception as exc:
        conn.send(("error", f"{type(exc).__name__}: {exc}"))
    else:
        conn.send(("ok", result))
    finally:
        conn.close()
