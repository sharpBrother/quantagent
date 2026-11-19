"""一次性迁移旧库 WGC 源记录；保留旧值、旧日期和来源。"""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from quantagent.adapters.postgres.src_targets import WGC_GOLD_DEMAND
from quantagent.adapters.postgres.src_write import PostgresSrcStore
from quantagent.ingest.sources.macro.wgc_legacy import read_wgc_legacy
from quantagent.ingest.writers.src_insert import write_src_snapshot
from quantagent.platform.errors import RunLogError
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from quantagent.ingest.writers.src_insert import SrcWriteResult
    from quantagent.ingest.writers.store import SrcWriteStore
    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths


def ingest_wgc_legacy(
    *,
    settings: Settings,
    paths: VarPaths,
    write_db: bool = False,
    fetch: Callable[[], Sequence[Mapping[str, object]]] | None = None,
    store: SrcWriteStore | None = None,
) -> SrcWriteResult:
    """首次载入是单事务；目标键已存在时停止，绝不覆盖。"""
    started = datetime.now(UTC)
    result: SrcWriteResult | None = None
    owned_conn = None
    try:
        rows = (fetch or (lambda: read_wgc_legacy(settings)))()
        if write_db and store is None:
            owned_conn = connect(settings, "src")
            store = PostgresSrcStore(owned_conn)
        result = write_src_snapshot(
            spec=WGC_GOLD_DEMAND, rows=rows, settings=settings, write_db=write_db, store=store
        )
    except Exception as exc:
        finished = datetime.now(UTC)
        with suppress(RunLogError):
            persist_run_log(
                RunLog(
                    action="ingest.macro.wgc_legacy",
                    status="failure",
                    started_at=started,
                    finished_at=finished,
                    elapsed_ms=int((finished - started).total_seconds() * 1000),
                    error=type(exc).__name__,
                ),
                paths,
            )
        raise
    finally:
        if owned_conn is not None:
            owned_conn.close()
    finished = datetime.now(UTC)
    persist_run_log(
        RunLog(
            action="ingest.macro.wgc_legacy",
            status="success",
            started_at=started,
            finished_at=finished,
            elapsed_ms=int((finished - started).total_seconds() * 1000),
            input_digest=result.payload_digest,
            output_digest=result.output_digest,
            row_count=result.row_count,
            dml_count=result.dml_count,
        ),
        paths,
    )
    return result
