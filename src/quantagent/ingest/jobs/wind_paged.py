"""Wind ``OPDATE + OBJECT_ID`` 分页采集。历史回填与日更共用。"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from quantagent.adapters.postgres.src_write import PostgresSrcStore
from quantagent.ingest.errors import SourceFetchError
from quantagent.ingest.sources.wind.client import open_wind_connection
from quantagent.ingest.sources.wind.cursor import decode_cursor, initial_cursor
from quantagent.ingest.sources.wind.paged import PymssqlWindPageSource
from quantagent.ingest.sources.wind.tables import resolve_wind_paged_table
from quantagent.ingest.writers.wind_page import write_wind_page
from quantagent.platform.errors import RunLogError
from quantagent.platform.identity import digest_json
from quantagent.platform.pg import connect, plane_configured
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Callable

    from quantagent.adapters.postgres.src_targets import SrcTableWriteSpec
    from quantagent.ingest.sources.wind.cursor import WindCursor
    from quantagent.ingest.sources.wind.paged import WindPageSource
    from quantagent.ingest.sources.wind.tables import WindPagedTable
    from quantagent.ingest.writers.store import SrcWriteStore
    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

ACTION = "ingest.wind.paged"
DEFAULT_PAGE_SIZE = 1000


@dataclass(frozen=True)
class WindPagedIngestResult:
    dataset: str
    table: str
    written: bool
    pages: int
    row_count: int
    inserted: int
    replaced: int
    deleted: int
    skipped: int
    dml_count: int
    payload_digest: str
    output_digest: str
    source_cursor: str
    replace_existing: bool


def ingest_wind_paged(
    *,
    settings: Settings,
    paths: VarPaths,
    table: str,
    write_db: bool = False,
    replace_existing: bool = False,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int | None = None,
    from_cursor: str | None = None,
    source: WindPageSource | None = None,
    store: SrcWriteStore | None = None,
    now: Callable[[], datetime] | None = None,
) -> WindPagedIngestResult:
    started = datetime.now(UTC)
    catalog = resolve_wind_paged_table(table)
    page_limit = _resolve_max_pages(write_db=write_db, max_pages=max_pages)
    owned_wind = None
    owned_pg = None
    resolved_source = source
    resolved_store = store
    try:
        if resolved_source is None:
            owned_wind = open_wind_connection(settings)
            resolved_source = PymssqlWindPageSource(owned_wind)
        if resolved_store is None and (
            write_db or (from_cursor is None and plane_configured(settings, "src"))
        ):
            owned_pg = connect(settings, "src")
            resolved_store = PostgresSrcStore(owned_pg)
        cursor = _start_cursor(resolved_store, catalog.spec, from_cursor)
        result = _run_pages(
            settings=settings,
            catalog=catalog,
            source=resolved_source,
            store=resolved_store,
            cursor=cursor,
            write_db=write_db,
            replace_existing=replace_existing,
            page_size=page_size,
            max_pages=page_limit,
            now=now,
        )
    except Exception as exc:
        with suppress(RunLogError):
            _persist_run_log(
                paths=paths,
                started=started,
                table=table,
                dataset=catalog.spec.dataset,
                write_db=write_db,
                replace_existing=replace_existing,
                page_size=page_size,
                max_pages=page_limit,
                from_cursor=from_cursor,
                status="failure",
                error=str(exc),
            )
        raise
    finally:
        if owned_wind is not None:
            owned_wind.close()
        if owned_pg is not None:
            owned_pg.close()
    _persist_run_log(
        paths=paths,
        started=started,
        table=table,
        dataset=catalog.spec.dataset,
        write_db=write_db,
        replace_existing=replace_existing,
        page_size=page_size,
        max_pages=page_limit,
        from_cursor=from_cursor,
        status="success",
        result=result,
    )
    return result


def _run_pages(
    *,
    settings: Settings,
    catalog: WindPagedTable,
    source: WindPageSource,
    store: SrcWriteStore | None,
    cursor: WindCursor,
    write_db: bool,
    replace_existing: bool,
    page_size: int,
    max_pages: int | None,
    now: Callable[[], datetime] | None,
) -> WindPagedIngestResult:
    pages = 0
    row_count = 0
    inserted = 0
    replaced = 0
    deleted = 0
    skipped = 0
    dml_count = 0
    last_digest = digest_json([])
    last_output = last_digest
    current = cursor
    while max_pages is None or pages < max_pages:
        rows = source.fetch_page(
            table=catalog.source_table,
            columns=catalog.spec.native_columns,
            cursor=current,
            limit=page_size,
            chi_fields=catalog.chi_fields,
        )
        if not rows:
            break
        page = write_wind_page(
            spec=catalog.spec,
            rows=rows,
            settings=settings,
            write_db=write_db,
            replace_existing=replace_existing,
            store=store,
            now=now,
        )
        pages += 1
        row_count += page.row_count
        inserted += page.inserted
        replaced += page.replaced
        deleted += page.deleted
        skipped += page.skipped
        dml_count += page.dml_count
        last_digest = page.payload_digest
        last_output = page.output_digest
        current = decode_cursor(page.source_cursor)
    output = digest_json(
        {
            "dataset": catalog.spec.dataset,
            "pages": pages,
            "row_count": row_count,
            "inserted": inserted,
            "replaced": replaced,
            "deleted": deleted,
            "skipped": skipped,
            "source_cursor": current.encode(),
            "last_page": last_output,
        }
    )
    return WindPagedIngestResult(
        dataset=catalog.spec.dataset,
        table=catalog.source_table,
        written=write_db and dml_count > 0,
        pages=pages,
        row_count=row_count,
        inserted=inserted,
        replaced=replaced,
        deleted=deleted,
        skipped=skipped,
        dml_count=dml_count,
        payload_digest=last_digest,
        output_digest=output,
        source_cursor=current.encode(),
        replace_existing=replace_existing,
    )


def _start_cursor(
    store: SrcWriteStore | None,
    spec: SrcTableWriteSpec,
    from_cursor: str | None,
) -> WindCursor:
    if from_cursor is not None:
        return decode_cursor(from_cursor)
    if store is None:
        return initial_cursor()
    return decode_cursor(store.latest_source_cursor(spec))


def _resolve_max_pages(*, write_db: bool, max_pages: int | None) -> int | None:
    if max_pages is None:
        return 1 if not write_db else None
    if max_pages < 1:
        raise SourceFetchError(f"max_pages 必须 >= 1: {max_pages}")
    return max_pages


def _persist_run_log(
    *,
    paths: VarPaths,
    started: datetime,
    table: str,
    dataset: str,
    write_db: bool,
    replace_existing: bool,
    page_size: int,
    max_pages: int | None,
    from_cursor: str | None,
    status: Literal["success", "failure"],
    result: WindPagedIngestResult | None = None,
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
                "dataset": dataset,
                "table": table,
                "write_db": write_db,
                "replace_existing": replace_existing,
                "page_size": page_size,
                "max_pages": max_pages,
                "from_cursor": from_cursor,
            }
        ),
        output_digest=None if result is None else result.output_digest,
        row_count=None if result is None else result.row_count,
        dml_count=0 if result is None else result.dml_count,
        error=error,
    )
    persist_run_log(record, paths)
