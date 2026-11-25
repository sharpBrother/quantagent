"""Wind 采集与日历物化的注入点。

资产函数只从这里取依赖。测试传入假源和临时目录；正式定义不传，
业务函数自己打开连接。写库开关仍由 ``ingest_wind_paged`` 执行。
看门狗的通用部分在 ``orchestration.resources.watchdog``，聚源共用。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from orchestration.resources.watchdog import (
    POLL_SECONDS,
    TERM_GRACE_SECONDS,
    PageProgress,
    last_progress_time,
    run_watched_child,
)

# 测试直接从本模块导入这个名字；看门狗实现已移到 watchdog。
_last_progress_time = last_progress_time

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
        stop_run_id: str | None = None,
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
            stop_run_id=stop_run_id,
        )

    def _run_watched(
        self,
        table: str,
        *,
        write_db: bool,
        page_size: int,
        max_pages: int | None,
        stop_run_id: str | None = None,
        child_target: Callable[..., None] | None = None,
        poll_seconds: float = POLL_SECONDS,
        term_grace_seconds: float = TERM_GRACE_SECONDS,
    ) -> WindPagedIngestResult:
        """在子进程里跑 Wind 采集，无新页超时即终止，语义见 ``run_watched_child``。

        ``child_target`` 与轮询、宽限期参数仅供测试替换子进程函数和缩短等待时间。
        """
        from quantagent.ingest.jobs.wind_control import wind_stop_path

        target = child_target if child_target is not None else _ingest_child
        progress_dir = self._paths.logs / "wind_ingest_progress"
        # 停止标记要放在进度目录里，先建目录再触碰文件。
        progress_dir.mkdir(parents=True, exist_ok=True)
        child_kwargs: dict[str, object] = {
            "settings": self._settings,
            "paths": self._paths,
            "table": table,
            "write_db": write_db,
            "page_size": page_size,
            "max_pages": max_pages,
        }
        if stop_run_id is not None:
            stop_path = wind_stop_path(self._paths, stop_run_id)
            # 留存运行级能力标记，避免向仍使用旧代码的 run 发出无效停止请求。
            stop_path.with_suffix(".ready").touch(exist_ok=True)
            child_kwargs["stop_path"] = stop_path
        return cast(
            "WindPagedIngestResult",
            run_watched_child(
                table=table,
                progress_dir=progress_dir,
                child_target=target,
                child_kwargs=child_kwargs,
                stall_seconds=self._stall_seconds,
                poll_seconds=poll_seconds,
                term_grace_seconds=term_grace_seconds,
            ),
        )


class _PageProgress(PageProgress):
    """Wind 子进程的进度写入器：提交计数之外，还检查停止标记。"""

    def __init__(self, progress_path: Path, stop_path: Path | None = None) -> None:
        super().__init__(progress_path)
        self.stop_path = stop_path

    def __call__(self, pages: int) -> None:
        super().__call__(pages)
        # 只在页事务返回之后响应；第 0 次调用则在打开数据连接之前检查。
        if self.stop_path is not None and self.stop_path.exists():
            from quantagent.ingest.errors import IngestStoppedError

            raise IngestStoppedError(f"按请求停止，已提交 {pages} 页；下次从已提交游标续跑")


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
    stop_path: Path | None = None,
) -> None:
    """子进程入口。必须是模块顶层函数，spawn 方式才能按名字导入它。"""
    from quantagent.ingest.errors import IngestStoppedError
    from quantagent.ingest.jobs.wind_paged import ingest_wind_paged

    progress = _PageProgress(progress_path, stop_path)
    try:
        progress(0)
        progress.mark_phase("initializing", 1)
        result = ingest_wind_paged(
            settings=settings,
            paths=paths,
            table=table,
            write_db=write_db,
            page_size=page_size,
            max_pages=max_pages,
            on_page=progress,
        )
    except IngestStoppedError as exc:
        conn.send(("stopped", str(exc)))
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
