"""Wind 一页写入。

默认 insert-only。目标键已有且内容变了，或源端 ``OPMODE=2``，必须显式
``replace_existing``。相同内容跳过，不算覆盖。游标写在 ``_batch.source_cursor``，
提交成功才算推进——页内崩溃回滚后下次从同一复合键重读。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from quantagent.adapters.postgres.errors import SrcConflictError, TransactionUnknownError
from quantagent.ingest.errors import (
    EmptyPayloadError,
    IngestError,
    ReadbackError,
    ReplaceRequiredError,
    SourceFetchError,
)
from quantagent.ingest.sources.wind.cursor import WindCursor, cursor_from_row
from quantagent.ingest.writers.src_insert import (
    payload_digest,
    reject_duplicate_payload_keys,
    require_native_rows,
    row_hash,
)
from quantagent.ingest.writers.tables import assert_writable
from quantagent.platform.config.write_gate import assert_db_write_allowed
from quantagent.platform.identity import digest_json

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from quantagent.adapters.postgres.src_targets import SrcTableWriteSpec
    from quantagent.ingest.writers.store import SrcWriteStore
    from quantagent.platform.config.settings import Settings

OpMode = Literal[0, 1, 2]
OPMODE_INSERT: OpMode = 0
OPMODE_UPDATE: OpMode = 1
OPMODE_DELETE: OpMode = 2


@dataclass(frozen=True)
class WindPageWriteResult:
    dataset: str
    written: bool
    row_count: int
    inserted: int
    replaced: int
    deleted: int
    skipped: int
    payload_digest: str
    output_digest: str
    dml_count: int
    batch_id: int | None
    hashes: tuple[str, ...]
    source_cursor: str


def write_wind_page(
    *,
    spec: SrcTableWriteSpec,
    rows: Sequence[Mapping[str, object]],
    settings: Settings,
    write_db: bool,
    replace_existing: bool = False,
    store: SrcWriteStore | None = None,
    now: Callable[[], datetime] | None = None,
) -> WindPageWriteResult:
    """一页一行事务。``write_db`` 默认由调用方传 False。"""
    assert_writable(spec)
    if "OBJECT_ID" not in spec.native_columns or "OPDATE" not in spec.native_columns:
        raise SourceFetchError(f"{spec.dataset} 缺少 OBJECT_ID/OPDATE，不能走复合游标")
    if "OPMODE" not in spec.native_columns:
        raise SourceFetchError(f"{spec.dataset} 缺少 OPMODE")
    native_rows = require_native_rows(spec, rows)
    if not native_rows:
        raise EmptyPayloadError(f"{spec.dataset} 页载荷为空")
    reject_duplicate_payload_keys(spec, native_rows)
    end_cursor = cursor_from_row(native_rows[-1])
    plan = _plan_page(spec, native_rows, replace_existing=replace_existing)
    digest = payload_digest(native_rows, spec.native_columns)
    if not write_db:
        return _result(
            spec=spec,
            written=False,
            plan=plan,
            digest=digest,
            output_digest=digest,
            dml_count=0,
            batch_id=None,
            hashes=plan.insert_hashes,
            cursor=end_cursor,
        )
    assert_db_write_allowed(settings=settings, write_db=True)
    if store is None:
        raise IngestError("write_db 为真时必须提供 SrcWriteStore")
    existing = store.existing_hashes(spec, [item.key for item in plan.items])
    plan = _apply_existing(spec, plan, existing, replace_existing=replace_existing)
    clock = now or (lambda: datetime.now(UTC))
    started_at = clock()
    finished_at = clock()
    window_start, window_end = _trade_window(native_rows)
    batch_id = store.insert_batch(
        spec=spec,
        window_start=window_start,
        window_end=window_end,
        row_count=len(native_rows),
        payload_digest=digest,
        started_at=started_at,
        finished_at=finished_at,
        source_cursor=end_cursor.encode(),
    )
    dml_count = 1
    try:
        if plan.delete_keys:
            store.delete_keys(spec, plan.delete_keys)
            dml_count += 1
        if plan.insert_rows:
            store.insert_rows(
                spec,
                plan.insert_rows,
                hashes=plan.insert_hashes,
                batch_id=batch_id,
                ingested_at=finished_at,
            )
            dml_count += 1
    except SrcConflictError as exc:
        _rollback_or_unknown(store)
        raise ReplaceRequiredError(f"{spec.dataset} 插入时撞上已有键，已回滚") from exc
    readback = store.readback_hashes(spec, batch_id)
    if len(readback) != len(plan.insert_hashes) or sorted(readback) != sorted(plan.insert_hashes):
        _rollback_or_unknown(store)
        raise ReadbackError(
            f"{spec.dataset} 回读不一致：wrote={len(plan.insert_hashes)} read={len(readback)}"
        )
    try:
        store.commit()
    except TransactionUnknownError:
        raise
    output = digest_json(
        {
            "batch_id": batch_id,
            "row_count": len(native_rows),
            "digest": digest,
            "source_cursor": end_cursor.encode(),
        }
    )
    return _result(
        spec=spec,
        written=True,
        plan=plan,
        digest=digest,
        output_digest=output,
        dml_count=dml_count,
        batch_id=batch_id,
        hashes=plan.insert_hashes,
        cursor=end_cursor,
    )


def parse_opmode(value: object) -> OpMode:
    if isinstance(value, bytes):
        try:
            value = value.decode("ascii")
        except UnicodeDecodeError as exc:
            raise SourceFetchError(f"OPMODE 无法解码: {value!r}") from exc
    if value is None:
        raise SourceFetchError("OPMODE 为空")
    text = str(value).strip()
    mapping: dict[str, OpMode] = {
        "0": OPMODE_INSERT,
        "1": OPMODE_UPDATE,
        "2": OPMODE_DELETE,
    }
    parsed = mapping.get(text)
    if parsed is None:
        raise SourceFetchError(f"OPMODE 非法: {value!r}")
    return parsed


@dataclass(frozen=True)
class _RowPlan:
    key: tuple[object, ...]
    row: dict[str, object]
    digest: str
    opmode: OpMode


@dataclass(frozen=True)
class _PagePlan:
    items: tuple[_RowPlan, ...]
    insert_rows: tuple[dict[str, object], ...]
    insert_hashes: tuple[str, ...]
    delete_keys: tuple[tuple[object, ...], ...]
    inserted: int
    replaced: int
    deleted: int
    skipped: int


def _plan_page(
    spec: SrcTableWriteSpec,
    rows: Sequence[dict[str, object]],
    *,
    replace_existing: bool,
) -> _PagePlan:
    items: list[_RowPlan] = []
    for row in rows:
        opmode = parse_opmode(row["OPMODE"])
        key = tuple(row[name] for name in spec.keys)
        items.append(
            _RowPlan(key=key, row=row, digest=row_hash(row, spec.native_columns), opmode=opmode)
        )
    deletes = [item for item in items if item.opmode == OPMODE_DELETE]
    if deletes and not replace_existing:
        sample = ", ".join(repr(item.key) for item in deletes[:5])
        raise ReplaceRequiredError(f"{spec.dataset} 含 OPMODE=2，需要 --replace-existing: {sample}")
    return _PagePlan(
        items=tuple(items),
        insert_rows=tuple(item.row for item in items if item.opmode != OPMODE_DELETE),
        insert_hashes=tuple(item.digest for item in items if item.opmode != OPMODE_DELETE),
        delete_keys=tuple(item.key for item in deletes),
        inserted=sum(1 for item in items if item.opmode != OPMODE_DELETE),
        replaced=0,
        deleted=len(deletes),
        skipped=0,
    )


def _apply_existing(
    spec: SrcTableWriteSpec,
    plan: _PagePlan,
    existing: dict[tuple[object, ...], str],
    *,
    replace_existing: bool,
) -> _PagePlan:
    insert_rows: list[dict[str, object]] = []
    insert_hashes: list[str] = []
    delete_keys: list[tuple[object, ...]] = []
    inserted = 0
    replaced = 0
    deleted = 0
    skipped = 0
    changed: list[tuple[object, ...]] = []
    for item in plan.items:
        current = existing.get(item.key)
        if item.opmode == OPMODE_DELETE:
            deleted += 1
            if current is not None:
                delete_keys.append(item.key)
            continue
        if current is None:
            insert_rows.append(item.row)
            insert_hashes.append(item.digest)
            inserted += 1
            continue
        if current == item.digest:
            skipped += 1
            continue
        changed.append(item.key)
        if not replace_existing:
            continue
        delete_keys.append(item.key)
        insert_rows.append(item.row)
        insert_hashes.append(item.digest)
        replaced += 1
    if changed and not replace_existing:
        sample = ", ".join(repr(key) for key in changed[:5])
        raise ReplaceRequiredError(f"{spec.dataset} 目标键已存在且内容变了，拒绝覆盖: {sample}")
    return _PagePlan(
        items=plan.items,
        insert_rows=tuple(insert_rows),
        insert_hashes=tuple(insert_hashes),
        delete_keys=tuple(delete_keys),
        inserted=inserted,
        replaced=replaced,
        deleted=deleted,
        skipped=skipped,
    )


def _trade_window(rows: Sequence[Mapping[str, object]]) -> tuple[str | None, str | None]:
    dates = [
        str(row["TRADE_DT"])
        for row in rows
        if isinstance(row.get("TRADE_DT"), str) and row["TRADE_DT"]
    ]
    if not dates:
        return None, None
    text_dates = [str(item) for item in dates]
    return min(text_dates), max(text_dates)


def _result(
    *,
    spec: SrcTableWriteSpec,
    written: bool,
    plan: _PagePlan,
    digest: str,
    output_digest: str,
    dml_count: int,
    batch_id: int | None,
    hashes: tuple[str, ...],
    cursor: WindCursor,
) -> WindPageWriteResult:
    return WindPageWriteResult(
        dataset=spec.dataset,
        written=written,
        row_count=len(plan.items),
        inserted=plan.inserted,
        replaced=plan.replaced,
        deleted=plan.deleted,
        skipped=plan.skipped,
        payload_digest=digest,
        output_digest=output_digest,
        dml_count=dml_count,
        batch_id=batch_id,
        hashes=hashes,
        source_cursor=cursor.encode(),
    )


def _rollback_or_unknown(store: SrcWriteStore) -> None:
    store.rollback()
