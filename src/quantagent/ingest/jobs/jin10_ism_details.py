"""已知金十 ISM 事件采集；不猜测或自动生成事件 ID。"""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from quantagent.adapters.postgres.src_targets import JIN10_ECONOMIC_CALENDAR
from quantagent.adapters.postgres.src_write import PostgresSrcStore
from quantagent.ingest.errors import EmptyPayloadError, IngestError
from quantagent.ingest.sources.macro.jin10_ism import INDICATOR_ID, fetch_jin10_ism_detail
from quantagent.ingest.writers.src_insert import write_src_snapshot
from quantagent.platform.errors import RunLogError
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from quantagent.ingest.sources.macro.jin10_ism import Jin10IsmDetail
    from quantagent.ingest.writers.src_insert import SrcWriteResult
    from quantagent.ingest.writers.store import SrcWriteStore
    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths


def ingest_jin10_ism_details(
    *,
    settings: Settings,
    paths: VarPaths,
    event_ids: Sequence[int],
    write_db: bool = False,
    fetch: Callable[[int], Jin10IsmDetail] = fetch_jin10_ism_detail,
    store: SrcWriteStore | None = None,
) -> SrcWriteResult:
    """只读源端详情；默认干跑，重复键和内容冲突均由写入器拒绝。"""
    started = datetime.now(UTC)
    conn = None
    try:
        if not event_ids:
            raise EmptyPayloadError("金十 ISM 未提供事件 ID")
        if len(set(event_ids)) != len(event_ids):
            raise IngestError("金十 ISM 事件 ID 重复")
        records = []
        for event_id in event_ids:
            item = fetch(event_id)
            if item.data_id != event_id:
                raise IngestError("金十 ISM 事件身份不匹配")
            records.append(
                {
                    "indicator_id": INDICATOR_ID,
                    "publish_date": item.publish_date,
                    "data_id": item.data_id,
                    "period_end": item.period_end,
                    "time_period": item.time_period,
                    "published_at": item.published_at,
                    "actual_value": item.actual_value,
                    "forecast_value": item.forecast_value,
                    "previous_value": item.previous_value,
                    "revised_value": item.revised_value,
                    "source": "jin10.economic_calendar",
                }
            )
        if write_db and store is None:
            conn = connect(settings, "src")
            store = PostgresSrcStore(conn)
        result = write_src_snapshot(
            spec=JIN10_ECONOMIC_CALENDAR,
            rows=records,
            settings=settings,
            write_db=write_db,
            store=store,
        )
    except Exception as exc:
        finished = datetime.now(UTC)
        with suppress(RunLogError):
            persist_run_log(
                RunLog(
                    action="ingest.macro.jin10_ism_details",
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
        if conn is not None:
            conn.close()
    finished = datetime.now(UTC)
    persist_run_log(
        RunLog(
            action="ingest.macro.jin10_ism_details",
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
