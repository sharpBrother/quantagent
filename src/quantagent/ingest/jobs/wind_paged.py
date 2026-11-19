"""Wind ``OPDATE + OBJECT_ID`` 分页采集。历史回填与日更共用。"""

from __future__ import annotations

import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from quantagent.adapters.postgres.src_write import PostgresSrcStore
from quantagent.ingest.errors import SourceFetchError
from quantagent.ingest.sources.wind.client import open_wind_connection
from quantagent.ingest.sources.wind.cursor import cursor_from_row, decode_cursor, initial_cursor
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
_SLOW_STAGE_SECONDS = 30.0
_LOG = logging.getLogger(__name__)


@dataclass
class _CommittedPages:
    """``write_wind_page`` 已返回的页。返回即该页已提交，页尾游标可记入日志。"""

    pages: int = 0
    row_count: int = 0
    inserted: int = 0
    replaced: int = 0
    deleted: int = 0
    skipped: int = 0
    metadata_skipped: int = 0
    dml_count: int = 0
    last_digest: str = ""
    last_output: str = ""
    cursor: WindCursor | None = None


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
    metadata_skipped: int
    dml_count: int
    payload_digest: str
    output_digest: str
    source_cursor: str


def ingest_wind_paged(
    *,
    settings: Settings,
    paths: VarPaths,
    table: str,
    write_db: bool = False,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int | None = None,
    from_cursor: str | None = None,
    source: WindPageSource | None = None,
    store: SrcWriteStore | None = None,
    now: Callable[[], datetime] | None = None,
    on_page: Callable[[int], None] | None = None,
) -> WindPagedIngestResult:
    started = datetime.now(UTC)
    catalog = resolve_wind_paged_table(table)
    page_limit = _resolve_max_pages(write_db=write_db, max_pages=max_pages)
    owned_wind = None
    owned_pg = None
    resolved_source = source
    resolved_store = store
    committed: _CommittedPages | None = None
    try:
        if resolved_source is None:
            owned_wind = open_wind_connection(settings)
            resolved_source = PymssqlWindPageSource(owned_wind)
        if resolved_store is None and (
            write_db or (from_cursor is None and plane_configured(settings, "src"))
        ):
            owned_pg = connect(settings, "src")
            resolved_store = PostgresSrcStore(owned_pg)
        if owned_pg is not None and write_db:
            # 转发吞掉的连接会留下孤儿事务，若它仍持有本页主键，重试会在唯一索引上等锁。
            # 这里只限制等锁时长；正常写入不等锁，不影响 30 秒级的页。
            # psycopg 默认非自动提交，SET 必须单独提交，否则会和第一页落在同一事务里。
            owned_pg.execute("SET lock_timeout = '60s'")
            owned_pg.commit()
        cursor = _start_cursor(resolved_store, catalog.spec, from_cursor)
        _assert_source_columns(resolved_source, catalog.spec)
        committed = _CommittedPages(cursor=cursor)
        result = _run_pages(
            settings=settings,
            catalog=catalog,
            source=resolved_source,
            store=resolved_store,
            cursor=cursor,
            write_db=write_db,
            page_size=page_size,
            max_pages=page_limit,
            now=now,
            committed=committed,
            on_page=on_page,
        )
    except Exception as exc:
        # 已返回的页已经提交。正在写入的页，尤其是提交结果未知的页，不计入日志，也不重试。
        partial = _partial_result(
            catalog=catalog,
            write_db=write_db,
            committed=committed,
        )
        error = str(exc)
        if partial is not None:
            error = (
                f"{exc}；已提交页 pages={partial.pages} row_count={partial.row_count} "
                f"dml_count={partial.dml_count} source_cursor={partial.source_cursor}"
            )
        with suppress(RunLogError):
            _persist_run_log(
                paths=paths,
                started=started,
                table=table,
                dataset=catalog.spec.dataset,
                write_db=write_db,
                page_size=page_size,
                max_pages=page_limit,
                from_cursor=from_cursor,
                status="failure",
                result=partial,
                error=error,
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
    page_size: int,
    max_pages: int | None,
    now: Callable[[], datetime] | None,
    committed: _CommittedPages,
    on_page: Callable[[int], None] | None = None,
) -> WindPagedIngestResult:
    pages = 0
    row_count = 0
    inserted = 0
    replaced = 0
    deleted = 0
    skipped = 0
    metadata_skipped = 0
    dml_count = 0
    last_digest = digest_json([])
    last_output = last_digest
    current = cursor
    while max_pages is None or pages < max_pages:
        # 阶段状态独立于已提交页的心跳，不能让慢查询掩盖看门狗超时。
        _mark_phase(on_page, "source_fetch", pages + 1, current.encode())
        stage_started = time.monotonic()
        rows = source.fetch_page(
            table=catalog.source_table,
            columns=catalog.spec.native_columns,
            cursor=current,
            limit=page_size,
            chi_fields=catalog.chi_fields,
        )
        _log_slow_stage(catalog.source_table, pages + 1, "source_fetch", stage_started)
        if not rows:
            break
        _mark_phase(
            on_page,
            "pg_write_and_verify" if write_db else "dry_run",
            pages + 1,
            current.encode(),
            cursor_from_row(rows[-1]).encode(),
        )
        stage_started = time.monotonic()
        page = write_wind_page(
            spec=catalog.spec,
            rows=rows,
            settings=settings,
            write_db=write_db,
            store=store,
            now=now,
        )
        _log_slow_stage(
            catalog.source_table,
            pages + 1,
            "pg_write_and_verify" if write_db else "dry_run",
            stage_started,
        )
        pages += 1
        row_count += page.row_count
        inserted += page.inserted
        replaced += page.replaced
        deleted += page.deleted
        skipped += page.skipped
        metadata_skipped += page.metadata_skipped
        dml_count += page.dml_count
        last_digest = page.payload_digest
        last_output = page.output_digest
        current = decode_cursor(page.source_cursor)
        # 只在本页函数返回后计入。提交结果未知时函数不会返回，该页不能记成已提交。
        committed.pages = pages
        committed.row_count = row_count
        committed.inserted = inserted
        committed.replaced = replaced
        committed.deleted = deleted
        committed.skipped = skipped
        committed.metadata_skipped = metadata_skipped
        committed.dml_count = dml_count
        committed.last_digest = last_digest
        committed.last_output = last_output
        committed.cursor = current
        # 放在本页已提交之后。调用方据此判断是否有新页，回调异常照常向外抛。
        if on_page is not None:
            on_page(pages)
    output = digest_json(
        {
            "dataset": catalog.spec.dataset,
            "pages": pages,
            "row_count": row_count,
            "inserted": inserted,
            "replaced": replaced,
            "deleted": deleted,
            "skipped": skipped,
            "metadata_skipped": metadata_skipped,
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
        metadata_skipped=metadata_skipped,
        dml_count=dml_count,
        payload_digest=last_digest,
        output_digest=output,
        source_cursor=current.encode(),
    )


def _mark_phase(
    on_page: Callable[[int], None] | None,
    phase: str,
    page: int,
    start_cursor: str,
    end_cursor: str | None = None,
) -> None:
    marker = getattr(on_page, "mark_phase", None)
    if callable(marker):
        marker(phase, page, start_cursor, end_cursor)


def _log_slow_stage(table: str, page: int, phase: str, started: float) -> None:
    elapsed = time.monotonic() - started
    if elapsed >= _SLOW_STAGE_SECONDS:
        _LOG.warning("Wind %s page=%d %s=%.1fs", table, page, phase, elapsed)


def _partial_result(
    *,
    catalog: WindPagedTable,
    write_db: bool,
    committed: _CommittedPages | None,
) -> WindPagedIngestResult | None:
    if committed is None or committed.pages == 0 or committed.cursor is None:
        return None
    output = digest_json(
        {
            "dataset": catalog.spec.dataset,
            "pages": committed.pages,
            "row_count": committed.row_count,
            "inserted": committed.inserted,
            "replaced": committed.replaced,
            "deleted": committed.deleted,
            "skipped": committed.skipped,
            "metadata_skipped": committed.metadata_skipped,
            "source_cursor": committed.cursor.encode(),
            "last_page": committed.last_output,
        }
    )
    return WindPagedIngestResult(
        dataset=catalog.spec.dataset,
        table=catalog.source_table,
        written=write_db and committed.dml_count > 0,
        pages=committed.pages,
        row_count=committed.row_count,
        inserted=committed.inserted,
        replaced=committed.replaced,
        deleted=committed.deleted,
        skipped=committed.skipped,
        metadata_skipped=committed.metadata_skipped,
        dml_count=committed.dml_count,
        payload_digest=committed.last_digest,
        output_digest=output,
        source_cursor=committed.cursor.encode(),
    )


def _assert_source_columns(source: WindPageSource, spec: SrcTableWriteSpec) -> None:
    reader = getattr(source, "source_columns", None)
    if reader is None:
        return
    actual = list(reader(spec.pg_table))
    expected = list(spec.native_columns)
    if not actual:
        raise SourceFetchError(f"{spec.pg_table} 在 wind_db 不存在")
    # SQL Server 标识符不分大小写，pymssql 按 SELECT 里写的名字回键名，
    # 所以源端的 MOPDATE 与 spec 里的 mopdate 是同一列，不算不一致。
    actual_keys = {name.lower() for name in actual}
    expected_keys = {name.lower() for name in expected}
    if actual_keys == expected_keys:
        return
    only_source = sorted({name for name in actual if name.lower() not in expected_keys})
    only_spec = sorted({name for name in expected if name.lower() not in actual_keys})
    raise SourceFetchError(
        f"{spec.pg_table} 列与源表不一致 source_only={only_source} spec_only={only_spec}"
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
