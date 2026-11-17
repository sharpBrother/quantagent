"""Wind 采集与日历物化的注入点。

资产函数只从这里取依赖。测试传入假源和临时目录；正式定义不传，
业务函数自己打开连接。写库开关仍由 ``ingest_wind_paged`` 执行。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.ingest.jobs.wind_paged import ingest_wind_paged
from quantagent.lake.materialize.trade_calendar import materialize_trade_calendar

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

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
    ) -> None:
        self._settings = settings
        self._paths = paths
        self._source = source
        self._store = store

    def ingest(
        self,
        table: str,
        *,
        write_db: bool,
        page_size: int,
        max_pages: int | None,
    ) -> WindPagedIngestResult:
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
        return materialize_trade_calendar(
            settings=self._settings,
            paths=self._paths,
            as_of=as_of,
            rebuild=rebuild,
            src_rows=self._src_rows,
            append_only=append_only,
            horizon_days=horizon_days,
        )
