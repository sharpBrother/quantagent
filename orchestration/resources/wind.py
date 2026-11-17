"""Wind 采集与日历物化的注入点。

资产函数只从这里取依赖。测试传入假源和临时目录；正式定义不传，
业务函数自己打开连接。写库开关仍由 ``ingest_wind_paged`` 执行。
"""

from __future__ import annotations

import functools
import multiprocessing
import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from datetime import date
    from multiprocessing.connection import Connection
    from pathlib import Path

    from quantagent.ingest.jobs.wind_paged import WindPagedIngestResult
    from quantagent.ingest.sources.wind.paged import WindPageSource
    from quantagent.ingest.writers.store import SrcWriteStore
    from quantagent.lake.materialize.trade_calendar import TradeCalendarMaterializeResult
    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths


class WindIngestResource:
    def __init__(
        self,
        *,
        settings: Settings,
        paths: VarPaths,
        source: WindPageSource | None = None,
        store: SrcWriteStore | None = None,
        stall_seconds: float = 600.0,
    ) -> None:
        self._settings = settings
        self._paths = paths
        self._source = source
        self._store = store
        self._stall_seconds = stall_seconds

    def ingest(
        self,
        table: str,
        *,
        write_db: bool,
        page_size: int,
        max_pages: int | None,
    ) -> WindPagedIngestResult:
        from quantagent.ingest.jobs.wind_paged import (
            ingest_wind_paged,
        )

        # 测试注入假源或假存储时，在本进程直接运行，不启子进程。
        if self._source is not None or self._store is not None:
            return ingest_wind_paged(
                settings=self._settings,
                paths=self._paths,
                table=table,
                write_db=write_db,
                page_size=page_size,
                max_pages=max_pages,
                source=self._source,
                store=self._store,
            )
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
        poll_seconds: float = 5.0,
    ) -> WindPagedIngestResult:
        """在子进程里跑采集，父进程盯着“有没有新页提交”，无进展超时就终止子进程。

        为什么用子进程：执行机经 ToDesk 端口转发连 PG，转发会吞掉连接。被吞的连接上，
        psycopg 调用永不返回，同一线程里无法中断，只能由别的进程终止它。
        为什么按“无进展”而不是总时长：全量回填一张表可达数小时，总时长上限会误杀正常作业。
        终止的安全性：每页一个事务，页在 write_wind_page 返回后才记为已提交；
        被终止时未提交的页由 PG 回滚，或随连接消失而丢弃，下次从游标续跑。

        ``child_target`` 与 ``poll_seconds`` 仅供测试替换子进程函数和缩短轮询间隔。
        """
        from quantagent.ingest.errors import IngestError, IngestStalledError

        target = child_target if child_target is not None else _ingest_child
        ctx = multiprocessing.get_context("spawn")
        progress_dir = self._paths.logs / "wind_ingest_progress"
        progress_dir.mkdir(parents=True, exist_ok=True)
        progress_path = progress_dir / f"{table}.{os.getpid()}.progress"
        recv_conn, send_conn = ctx.Pipe(duplex=False)
        proc = ctx.Process(
            target=target,
            kwargs={
                "settings": self._settings,
                "paths": self._paths,
                "table": table,
                "write_db": write_db,
                "page_size": page_size,
                "max_pages": max_pages,
                "progress_path": progress_path,
                "conn": send_conn,
            },
            name=f"wind-ingest-{table}",
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
                last = _last_progress_time(progress_path, started_wall)
                if time.time() - last > self._stall_seconds:
                    proc.kill()
                    proc.join(10)
                    raise IngestStalledError(
                        f"{table} 超过 {self._stall_seconds:.0f} 秒没有新页提交，"
                        "已终止子进程；已提交页不受影响，下次从游标续跑"
                    )
            try:
                kind, payload = recv_conn.recv()
            except EOFError:
                raise IngestError(f"采集子进程异常退出 exitcode={proc.exitcode}") from None
            if kind == "ok":
                result: WindPagedIngestResult = payload
                return result
            raise IngestError(str(payload))
        finally:
            if proc.is_alive():
                proc.kill()
                proc.join(10)
            recv_conn.close()
            progress_path.unlink(missing_ok=True)
            proc.close()


def _last_progress_time(progress_path: Path, started_wall: float) -> float:
    # 子进程开始前还没有进度文件，计时从启动时刻算起，覆盖子进程导入慢或卡死在连接上的情况。
    try:
        return progress_path.stat().st_mtime
    except FileNotFoundError:
        return started_wall


def _write_progress(progress_path: Path, pages: int) -> None:
    progress_path.write_text(str(pages), encoding="utf-8")


def _ingest_child(
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
    from quantagent.ingest.jobs.wind_paged import ingest_wind_paged

    progress_path.write_text("0", encoding="utf-8")
    try:
        result = ingest_wind_paged(
            settings=settings,
            paths=paths,
            table=table,
            write_db=write_db,
            page_size=page_size,
            max_pages=max_pages,
            on_page=functools.partial(_write_progress, progress_path),
        )
    except Exception as exc:
        conn.send(("error", f"{type(exc).__name__}: {exc}"))
    else:
        conn.send(("ok", result))
    finally:
        conn.close()


class TradeCalendarResource:
    def __init__(
        self,
        *,
        settings: Settings,
        paths: VarPaths,
        src_rows: Sequence[Mapping[str, object]] | None = None,
    ) -> None:
        self._settings = settings
        self._paths = paths
        self._src_rows = src_rows

    def materialize(
        self,
        *,
        as_of: date,
        rebuild: bool,
        append_only: bool = False,
        horizon_days: int | None = None,
    ) -> TradeCalendarMaterializeResult:
        from quantagent.lake.materialize.trade_calendar import (
            materialize_trade_calendar,
        )

        return materialize_trade_calendar(
            settings=self._settings,
            paths=self._paths,
            as_of=as_of,
            rebuild=rebuild,
            src_rows=self._src_rows,
            append_only=append_only,
            horizon_days=horizon_days,
        )
