"""聚源 JYDB 分页采集。首次回填与日常增量共用。

每页一个事务、一条 ``_batch``：游标写在 ``source_cursor``，提交成功才推进。
源端修订行会得到更大的 ``JSID``，因此日常增量从最后成功游标继续即可覆盖
修订；目标键已有的业务列变化由 ``write_src_follow`` 按主键删旧插新。
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from quantagent.adapters.postgres.src_targets import JYDB_SPECS
from quantagent.adapters.postgres.src_write import PostgresSrcStore
from quantagent.ingest.errors import SourceFetchError
from quantagent.ingest.sources.jydb.client import open_jydb_connection
from quantagent.ingest.sources.jydb.cursor import (
    JydbCursor,
    cursor_from_row,
    decode_cursor,
    initial_cursor,
)
from quantagent.ingest.sources.jydb.paged import PymssqlJydbPageSource
from quantagent.ingest.writers.src_follow import write_src_follow
from quantagent.platform.errors import RunLogError
from quantagent.platform.identity import digest_json
from quantagent.platform.pg import connect, plane_configured
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Callable

    from quantagent.adapters.postgres.src_targets import SrcTableWriteSpec
    from quantagent.ingest.sources.jydb.paged import JydbPageSource
    from quantagent.ingest.writers.store import SrcWriteStore
    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

ACTION = "ingest.jydb.paged"
DEFAULT_PAGE_SIZE = 1000


@dataclass(frozen=True)
class JydbPagedIngestResult:
    dataset: str
    table: str
    written: bool
    pages: int
    row_count: int
    inserted: int
    replaced: int
    skipped: int
    metadata_skipped: int
    dml_count: int
    batch_ids: tuple[int, ...]
    payload_digest: str
    output_digest: str
    source_cursor: str


def ingest_jydb_paged(  # noqa: PLR0915 - 单函数持有连接、页循环与失败日志，避免状态分散
    *,
    settings: Settings,
    paths: VarPaths,
    table: str,
    write_db: bool = False,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int | None = None,
    from_cursor: str | None = None,
    source: JydbPageSource | None = None,
    store: SrcWriteStore | None = None,
    now: Callable[[], datetime] | None = None,
    on_page: Callable[[int], None] | None = None,
) -> JydbPagedIngestResult:
    started = datetime.now(UTC)
    spec = _resolve_spec(table)
    page_limit = _resolve_max_pages(write_db=write_db, max_pages=max_pages)
    clock = now or (lambda: datetime.now(UTC))
    owned_source = None
    owned_pg = None
    resolved_source = source
    resolved_store = store
    pages = 0
    row_count = 0
    inserted = 0
    replaced = 0
    skipped = 0
    metadata_skipped = 0
    dml_count = 0
    batch_ids: list[int] = []
    page_digests: list[str] = []
    cursor: JydbCursor = initial_cursor()
    try:
        if resolved_source is None:
            owned_source = open_jydb_connection(settings)
            resolved_source = PymssqlJydbPageSource(owned_source)
        if resolved_store is None and (
            write_db or (from_cursor is None and plane_configured(settings, "src"))
        ):
            owned_pg = connect(settings, "src")
            resolved_store = PostgresSrcStore(owned_pg)
        _assert_source_columns(resolved_source, spec)
        null_jsid = resolved_source.null_jsid_count(spec.pg_table)
        if null_jsid:
            raise SourceFetchError(f"{spec.pg_table} 有 {null_jsid} 行 JSID 为空，无法分页")
        cursor = _start_cursor(resolved_store, spec, from_cursor)
        while page_limit is None or pages < page_limit:
            rows = resolved_source.fetch_page(
                table=spec.pg_table,
                columns=spec.native_columns,
                cursor=cursor,
                limit=page_size,
            )
            if not rows:
                break
            end_cursor = cursor_from_row(rows[-1])
            page_result = write_src_follow(
                spec=spec,
                rows=rows,
                settings=settings,
                write_db=write_db,
                store=resolved_store,
                window_start=str(cursor.jsid),
                window_end=str(end_cursor.jsid),
                source_cursor=end_cursor.encode(),
                now=clock,
            )
            pages += 1
            row_count += page_result.row_count
            inserted += page_result.inserted
            replaced += page_result.replaced
            skipped += page_result.skipped
            metadata_skipped += page_result.metadata_skipped
            dml_count += page_result.dml_count
            page_digests.append(page_result.payload_digest)
            if page_result.batch_id is not None:
                batch_ids.append(page_result.batch_id)
            cursor = end_cursor
            if on_page is not None:
                on_page(pages)
    except Exception as exc:
        with suppress(RunLogError):
            _persist_run_log(
                paths=paths,
                started=started,
                table=table,
                spec=spec,
                write_db=write_db,
                page_size=page_size,
                max_pages=page_limit,
                from_cursor=from_cursor,
                status="failure",
                pages=pages,
                row_count=row_count,
                inserted=inserted,
                replaced=replaced,
                skipped=skipped,
                metadata_skipped=metadata_skipped,
                dml_count=dml_count,
                batch_ids=batch_ids,
                payload_digest=digest_json(page_digests),
                source_cursor=cursor.encode(),
                error=str(exc),
            )
        raise
    finally:
        if owned_source is not None:
            owned_source.close()
        if owned_pg is not None:
            owned_pg.close()

    result = JydbPagedIngestResult(
        dataset=spec.dataset,
        table=table,
        written=write_db,
        pages=pages,
        row_count=row_count,
        inserted=inserted,
        replaced=replaced,
        skipped=skipped,
        metadata_skipped=metadata_skipped,
        dml_count=dml_count,
        batch_ids=tuple(batch_ids),
        payload_digest=digest_json(page_digests),
        output_digest=digest_json(
            {
                "dataset": spec.dataset,
                "pages": pages,
                "row_count": row_count,
                "batch_ids": batch_ids,
                "source_cursor": cursor.encode(),
            }
        ),
        source_cursor=cursor.encode(),
    )
    _persist_run_log(
        paths=paths,
        started=started,
        table=table,
        spec=spec,
        write_db=write_db,
        page_size=page_size,
        max_pages=page_limit,
        from_cursor=from_cursor,
        status="success",
        pages=pages,
        row_count=row_count,
        inserted=inserted,
        replaced=replaced,
        skipped=skipped,
        metadata_skipped=metadata_skipped,
        dml_count=dml_count,
        batch_ids=batch_ids,
        payload_digest=result.payload_digest,
        source_cursor=result.source_cursor,
        error=None,
    )
    return result


def _resolve_spec(table: str) -> SrcTableWriteSpec:
    spec = JYDB_SPECS.get(table)
    if spec is None:
        raise SourceFetchError(f"聚源表不在采集白名单: {table}")
    return spec


def _resolve_max_pages(*, write_db: bool, max_pages: int | None) -> int | None:
    if max_pages is None:
        return None if write_db else 1
    if max_pages < 1:
        raise SourceFetchError(f"max_pages 必须 >= 1: {max_pages}")
    return max_pages


def _assert_source_columns(source: JydbPageSource, spec: SrcTableWriteSpec) -> None:
    actual = source.source_columns(spec.pg_table)
    if tuple(actual) != spec.native_columns:
        raise SourceFetchError(
            f"{spec.pg_table} 源端列与代码不一致：源端={actual}，代码={list(spec.native_columns)}"
        )


def _start_cursor(
    store: SrcWriteStore | None,
    spec: SrcTableWriteSpec,
    from_cursor: str | None,
) -> JydbCursor:
    if from_cursor is not None:
        return decode_cursor(from_cursor)
    if store is None:
        return initial_cursor()
    return decode_cursor(store.latest_source_cursor(spec))


def _persist_run_log(
    *,
    paths: VarPaths,
    started: datetime,
    table: str,
    spec: SrcTableWriteSpec,
    write_db: bool,
    page_size: int,
    max_pages: int | None,
    from_cursor: str | None,
    status: str,
    pages: int,
    row_count: int,
    inserted: int,
    replaced: int,
    skipped: int,
    metadata_skipped: int,
    dml_count: int,
    batch_ids: list[int],
    payload_digest: str,
    source_cursor: str,
    error: str | None,
) -> None:
    finished = datetime.now(UTC)
    persist_run_log(
        RunLog(
            action=ACTION,
            status="success" if status == "success" else "failure",
            started_at=started,
            finished_at=finished,
            elapsed_ms=int((finished - started).total_seconds() * 1000),
            input_digest=digest_json(
                {
                    "dataset": spec.dataset,
                    "table": table,
                    "page_size": page_size,
                    "max_pages": max_pages,
                    "from_cursor": from_cursor,
                    "write_db": write_db,
                }
            ),
            output_digest=digest_json(
                {
                    "pages": pages,
                    "row_count": row_count,
                    "inserted": inserted,
                    "replaced": replaced,
                    "skipped": skipped,
                    "metadata_skipped": metadata_skipped,
                    "dml_count": dml_count,
                    "batch_ids": batch_ids,
                    "payload_digest": payload_digest,
                    "source_cursor": source_cursor,
                }
            ),
            row_count=row_count,
            dml_count=dml_count,
            error=error,
        ),
        paths,
    )
