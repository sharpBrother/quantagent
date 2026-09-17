"""Tushare 交易日历采集作业。CLI 与编排共用。"""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from quantagent.adapters.postgres.src_write import PostgresSrcStore
from quantagent.ingest.sources.tushare.trade_cal import (
    DEFAULT_EXCHANGES,
    fetch_trade_cal,
    open_tushare_client,
)
from quantagent.ingest.writers.src_insert import write_src_snapshot
from quantagent.ingest.writers.tables import TRADE_CAL
from quantagent.platform.errors import RunLogError
from quantagent.platform.identity import digest_json
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from quantagent.ingest.sources.tushare.trade_cal import TradeCalClient
    from quantagent.ingest.writers.src_insert import SrcWriteResult
    from quantagent.ingest.writers.store import SrcWriteStore
    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

ACTION = "ingest.tushare.trade_cal"


def ingest_tushare_trade_cal(
    *,
    settings: Settings,
    paths: VarPaths,
    write_db: bool = False,
    start_date: str,
    end_date: str,
    exchanges: Sequence[str] = DEFAULT_EXCHANGES,
    client: TradeCalClient | None = None,
    store: SrcWriteStore | None = None,
    now: Callable[[], datetime] | None = None,
) -> SrcWriteResult:
    started = datetime.now(UTC)
    owned_conn = None
    try:
        resolved_client = client or open_tushare_client(settings.tushare_token.get_secret_value())
        rows = fetch_trade_cal(
            resolved_client,
            start_date=start_date,
            end_date=end_date,
            exchanges=exchanges,
        )
        if write_db and store is None:
            owned_conn = connect(settings, "src")
            store = PostgresSrcStore(owned_conn)
        result = write_src_snapshot(
            spec=TRADE_CAL,
            rows=rows,
            settings=settings,
            write_db=write_db,
            store=store,
            window_start=start_date,
            window_end=end_date,
            now=now,
        )
    except Exception as exc:
        with suppress(RunLogError):
            _persist_run_log(
                paths=paths,
                started=started,
                start_date=start_date,
                end_date=end_date,
                exchanges=exchanges,
                write_db=write_db,
                status="failure",
                error=str(exc),
            )
        raise
    finally:
        if owned_conn is not None:
            owned_conn.close()
    _persist_run_log(
        paths=paths,
        started=started,
        start_date=start_date,
        end_date=end_date,
        exchanges=exchanges,
        write_db=write_db,
        status="success",
        result=result,
    )
    return result


def _persist_run_log(
    *,
    paths: VarPaths,
    started: datetime,
    start_date: str,
    end_date: str,
    exchanges: Sequence[str],
    write_db: bool,
    status: Literal["success", "failure"],
    result: SrcWriteResult | None = None,
    error: str | None = None,
) -> None:
    finished = datetime.now(UTC)
    record = RunLog(
        action=ACTION,
        status=status,
        started_at=started,
        finished_at=finished,
        elapsed_ms=int((finished - started).total_seconds() * 1000),
        input_digest=digest_json(
            {
                "dataset": TRADE_CAL.dataset,
                "start_date": start_date,
                "end_date": end_date,
                "exchanges": list(exchanges),
                "write_db": write_db,
            }
        ),
        output_digest=None if result is None else result.output_digest,
        row_count=None if result is None else result.row_count,
        dml_count=0 if result is None else result.dml_count,
        error=error,
    )
    persist_run_log(record, paths)
