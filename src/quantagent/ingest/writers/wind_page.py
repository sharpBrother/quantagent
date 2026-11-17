"""Wind 一页写入。源镜像跟随源端当前状态，全自动。

目标键已有：业务字段全部相等时跳过（只变系统列的计入 ``metadata_skipped``）；
业务字段有变化时同一事务内 DELETE+INSERT，计入 ``replaced``。源端 ``OPMODE=2``
按主键删除，计入 ``deleted``。不需要人工放开（见
docs/adr/2026-11-17-src-mirror-follows-source.md）。游标写在 ``_batch.source_cursor``，
提交成功才算推进——页内崩溃回滚后下次从同一复合键重读。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

import psycopg

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
# 诊断信息里最多列几个样例。
_SAMPLE = 5

# Wind 的同步簿记列：变更时间、变更类型和 Wind 内部时间戳。Wind 会对历史行重发 OPMODE=1，
# 业务字段不变、只刷新这些列。这类修订不写库，库里该行的这些列会旧于源端；游标存在 _batch，
# 不受影响。比较业务字段时排除这些列。
WIND_SYSTEM_COLUMNS: frozenset[str] = frozenset(
    {"OPDATE", "OPMODE", "gsUTime", "gsCTime", "mopdate"}
)


@dataclass(frozen=True)
class WindPageWriteResult:
    dataset: str
    written: bool
    row_count: int
    inserted: int
    replaced: int
    deleted: int
    skipped: int
    metadata_skipped: int
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
    plan = _plan_page(spec, native_rows)
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
    try:
        existing = store.existing_hashes(spec, [item.key for item in plan.items])
    except psycopg.errors.DataError as exc:
        _rollback_or_unknown(store)
        raise IngestError(_data_error_detail(spec, native_rows, exc)) from exc
    metadata_only = _metadata_only_keys(spec, plan, existing, store)
    plan = _apply_existing(plan, existing, metadata_only=metadata_only)
    clock = now or (lambda: datetime.now(UTC))
    started_at = clock()
    finished_at = clock()
    # 批次登记的是业务日期范围，日历源使用 TRADE_DAYS。
    date_field = "TRADE_DAYS" if "TRADE_DAYS" in spec.native_columns else "TRADE_DT"
    window_start, window_end = _trade_window(native_rows, date_field=date_field)
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
    dml_count = _apply_dml(
        spec, store, plan, native_rows, batch_id=batch_id, ingested_at=finished_at
    )
    insert_keys = [tuple(row[name] for name in spec.keys) for row in plan.insert_rows]
    readback = store.readback_hashes(spec, batch_id, insert_keys)
    if len(readback) != len(plan.insert_hashes) or sorted(readback) != sorted(plan.insert_hashes):
        # 先在同一事务里查清缺的行现在是什么状态，再回滚；只报前 5 个，供排查。
        detail = _readback_detail(spec, store, plan, readback, insert_keys)
        _rollback_or_unknown(store)
        raise ReadbackError(
            f"{spec.dataset} 回读不一致：wrote={len(plan.insert_hashes)} read={len(readback)} "
            f"inserted={plan.inserted} replaced={plan.replaced} deleted={plan.deleted}；{detail}"
        )
    # 指纹一致之后再逐列核对：执行机经端口转发写库，指纹列完好不代表业务列没被改坏。
    mismatched = store.mismatched_rows(spec, batch_id, plan.insert_rows)
    if mismatched:
        _rollback_or_unknown(store)
        raise ReadbackError(
            f"{spec.dataset} 回读逐列核对不一致 {len(mismatched)} 行，已回滚；"
            f"样例 {mismatched[:_SAMPLE]!r}"
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
    metadata_skipped: int = 0


def _plan_page(
    spec: SrcTableWriteSpec,
    rows: Sequence[dict[str, object]],
) -> _PagePlan:
    items: list[_RowPlan] = []
    for row in rows:
        opmode = parse_opmode(row["OPMODE"])
        key = tuple(row[name] for name in spec.keys)
        items.append(
            _RowPlan(key=key, row=row, digest=row_hash(row, spec.native_columns), opmode=opmode)
        )
    deletes = [item for item in items if item.opmode == OPMODE_DELETE]
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


def _metadata_only_keys(
    spec: SrcTableWriteSpec,
    plan: _PagePlan,
    existing: dict[tuple[object, ...], str],
    store: SrcWriteStore,
) -> set[tuple[object, ...]]:
    """指纹变了、但业务字段与库里逐列相等的键。"""
    changed = {
        item.key: item
        for item in plan.items
        if item.opmode != OPMODE_DELETE
        and (current := existing.get(item.key)) is not None
        and current != item.digest
    }
    if not changed:
        return set()
    business = tuple(
        name
        for name in spec.native_columns
        if name not in WIND_SYSTEM_COLUMNS and name not in spec.keys
    )
    stored = store.existing_values(spec, list(changed), business)
    # 逐列用 == 比较而不是重算指纹：库里 numeric 读回的 Decimal 标度可能与源端不同，
    # == 按数值比较，不会把 10.5 与 10.5000 误判为变化。
    return {
        key
        for key, item in changed.items()
        if (values := stored.get(key)) is not None
        and all(item.row[name] == value for name, value in zip(business, values, strict=True))
    }


def _apply_existing(
    plan: _PagePlan,
    existing: dict[tuple[object, ...], str],
    *,
    metadata_only: set[tuple[object, ...]],
) -> _PagePlan:
    insert_rows: list[dict[str, object]] = []
    insert_hashes: list[str] = []
    delete_keys: list[tuple[object, ...]] = []
    inserted = 0
    replaced = 0
    deleted = 0
    skipped = 0
    metadata_skipped = 0
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
        if item.key in metadata_only:
            metadata_skipped += 1
            continue
        # 业务字段变了：源镜像跟随源端，同一事务内删旧插新，写后回读照常校验。
        delete_keys.append(item.key)
        insert_rows.append(item.row)
        insert_hashes.append(item.digest)
        replaced += 1
    return _PagePlan(
        items=plan.items,
        insert_rows=tuple(insert_rows),
        insert_hashes=tuple(insert_hashes),
        delete_keys=tuple(delete_keys),
        inserted=inserted,
        replaced=replaced,
        deleted=deleted,
        skipped=skipped,
        metadata_skipped=metadata_skipped,
    )


def _trade_window(
    rows: Sequence[Mapping[str, object]], *, date_field: str
) -> tuple[str | None, str | None]:
    dates = [value for row in rows if isinstance(value := row.get(date_field), str) and value]
    if not dates:
        return None, None
    return min(dates), max(dates)


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
        metadata_skipped=plan.metadata_skipped,
        payload_digest=digest,
        output_digest=output_digest,
        dml_count=dml_count,
        batch_id=batch_id,
        hashes=hashes,
        source_cursor=cursor.encode(),
    )


def _apply_dml(
    spec: SrcTableWriteSpec,
    store: SrcWriteStore,
    plan: _PagePlan,
    native_rows: Sequence[Mapping[str, object]],
    *,
    batch_id: int,
    ingested_at: datetime,
) -> int:
    """按主键删、再插入。返回含批次登记在内的 DML 条数。失败时回滚。"""
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
                ingested_at=ingested_at,
            )
            dml_count += 1
    except SrcConflictError as exc:
        _rollback_or_unknown(store)
        raise ReplaceRequiredError(f"{spec.dataset} 插入时撞上已有键，已回滚") from exc
    except psycopg.errors.DataError as exc:
        _rollback_or_unknown(store)
        raise IngestError(_data_error_detail(spec, native_rows, exc)) from exc
    return dml_count


def _readback_detail(
    spec: SrcTableWriteSpec,
    store: SrcWriteStore,
    plan: _PagePlan,
    readback: Sequence[str],
    insert_keys: Sequence[tuple[object, ...]],
) -> str:
    seen = set(readback)
    missing = [
        key
        for key, digest in zip(insert_keys, plan.insert_hashes, strict=True)
        if digest not in seen
    ][:_SAMPLE]
    try:
        stored = store.existing_values(spec, missing, ("_batch_id", "_row_hash"))
    except Exception as exc:  # 诊断失败不能掩盖原错误
        return f"缺失样例 {missing!r}，查询现状失败: {exc}"
    return f"缺失样例 {[(key, stored.get(key)) for key in missing]!r}"


def _is_suspect(value: object) -> bool:
    if isinstance(value, str):
        return "\x00" in value or not value.isascii()
    return not isinstance(value, (int, float, Decimal, datetime, type(None)))


def _data_error_detail(
    spec: SrcTableWriteSpec, rows: Sequence[Mapping[str, object]], exc: Exception
) -> str:
    # PG 拒收参数时只给参数序号。这里扫一遍本页，找出不是常规类型、或含 NUL / 非 ASCII 的值。
    suspects = [
        f"{name}@{tuple(row[k] for k in spec.keys)!r}={type(value).__name__}:{value!r:.80}"
        for row in rows
        for name in spec.native_columns
        if _is_suspect(value := row[name])
    ][:_SAMPLE]
    return f"{spec.dataset} 参数被 PG 拒收：{exc}；可疑值 {suspects or '无'}"


def _rollback_or_unknown(store: SrcWriteStore) -> None:
    store.rollback()
