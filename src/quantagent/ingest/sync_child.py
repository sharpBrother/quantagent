"""jydb / suntime 手动采集的看门狗子进程入口。

CLI（``quantagent ingest jydb sync`` 等）与 Dagster 日更走同一条采集链路，连接被
ToDesk 吞掉时一样永不返回，不能只在调度侧防护。但 CLI 不能反向依赖 orchestration，
因此子进程入口放在 ingest 层。orchestration 的 ``resources.jydb`` / ``resources.suntime``
保留各自的子进程入口是因为它们的历史更久、且 Dagster 资产与测试已绑定那些路径；
两者逻辑一致，都调 ``ingest_*_paged`` 并用 ``PageProgress`` 报告。

这些函数必须是模块顶层函数，spawn 方式才能按名字导入。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.ingest.watchdog import PageProgress

if TYPE_CHECKING:
    from multiprocessing.connection import Connection
    from pathlib import Path

    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths


def jydb_sync_child(
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
    """jydb 手动采集子进程入口。"""
    # 子进程按名 spawn，函数体内导入让父进程 import 本模块时不拉起业务依赖。
    from quantagent.ingest.jobs.jydb_paged import ingest_jydb_paged  # noqa: PLC0415

    progress = PageProgress(progress_path)
    try:
        progress.mark_phase("initializing", 1)
        result = ingest_jydb_paged(
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


def suntime_sync_child(
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
    """朝阳永续手动采集子进程入口。"""
    from quantagent.ingest.jobs.suntime_paged import ingest_suntime_paged  # noqa: PLC0415

    progress = PageProgress(progress_path)
    try:
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


__all__ = ["jydb_sync_child", "suntime_sync_child"]
