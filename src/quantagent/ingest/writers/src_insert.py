"""insert-only 源表写入。六条铁律是函数内建行为，不是调用约定。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from quantagent.adapters.postgres.errors import SrcConflictError, TransactionUnknownError
from quantagent.ingest.errors import (
    DuplicateKeyError,
    EmptyPayloadError,
    IngestError,
    ReadbackError,
)
from quantagent.ingest.writers.tables import assert_writable
from quantagent.platform.config.write_gate import assert_db_write_allowed
from quantagent.platform.identity import digest_json

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from quantagent.adapters.postgres.src_targets import SrcTableWriteSpec
    from quantagent.ingest.writers.store import SrcWriteStore
    from quantagent.platform.config.settings import Settings

_TECH_COLUMNS = frozenset({"_batch_id", "_ingested_at", "_row_hash"})


@dataclass(frozen=True)
class SrcWriteResult:
    dataset: str
    written: bool
    row_count: int
    payload_digest: str
    output_digest: str
    dml_count: int
    batch_id: int | None
    hashes: tuple[str, ...]


def row_hash(row: Mapping[str, object], columns: tuple[str, ...]) -> str:
    return digest_json({column: row[column] for column in columns})


def payload_digest(rows: Sequence[Mapping[str, object]], columns: tuple[str, ...]) -> str:
    ordered = sorted(
        ({column: row[column] for column in columns} for row in rows),
        key=lambda item: tuple(_sort_token(item[column]) for column in columns),
    )
    return digest_json(ordered)


def write_src_snapshot(
    *,
    spec: SrcTableWriteSpec,
    rows: Sequence[Mapping[str, object]],
    settings: Settings,
    write_db: bool,
    store: SrcWriteStore | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    now: Callable[[], datetime] | None = None,
) -> SrcWriteResult:
    """``write_db`` 默认由调用方传 False。真写必须同时打开环境写闸。"""
    assert_writable(spec)
    native_rows = require_native_rows(spec, rows)
    if not native_rows:
        raise EmptyPayloadError(f"{spec.dataset} 载荷为空")
    reject_duplicate_payload_keys(spec, native_rows)
    hashes = tuple(row_hash(row, spec.native_columns) for row in native_rows)
    digest = payload_digest(native_rows, spec.native_columns)
    if not write_db:
        return SrcWriteResult(
            dataset=spec.dataset,
            written=False,
            row_count=len(native_rows),
            payload_digest=digest,
            output_digest=digest,
            dml_count=0,
            batch_id=None,
            hashes=hashes,
        )
    assert_db_write_allowed(settings=settings, write_db=True)
    if store is None:
        raise IngestError("write_db 为真时必须提供 SrcWriteStore")
    existing = store.existing_keys(
        spec,
        [tuple(row[key] for key in spec.keys) for row in native_rows],
    )
    if existing:
        sample = ", ".join(repr(key) for key in sorted(existing)[:5])
        raise DuplicateKeyError(f"{spec.dataset} 目标键已存在，拒绝覆盖: {sample}")
    clock = now or (lambda: datetime.now(UTC))
    started_at = clock()
    finished_at = clock()
    ingested_at = finished_at
    batch_id = store.insert_batch(
        spec=spec,
        window_start=window_start,
        window_end=window_end,
        row_count=len(native_rows),
        payload_digest=digest,
        started_at=started_at,
        finished_at=finished_at,
    )
    try:
        store.insert_rows(
            spec,
            native_rows,
            hashes=hashes,
            batch_id=batch_id,
            ingested_at=ingested_at,
        )
    except SrcConflictError as exc:
        _rollback_or_unknown(store)
        raise DuplicateKeyError(f"{spec.dataset} 插入时撞上已有键，已回滚") from exc
    readback = store.readback_hashes(spec, batch_id)
    if len(readback) != len(hashes) or sorted(readback) != sorted(hashes):
        _rollback_or_unknown(store)
        raise ReadbackError(f"{spec.dataset} 回读不一致：wrote={len(hashes)} read={len(readback)}")
    try:
        store.commit()
    except TransactionUnknownError:
        # 提交结果不确定时不能 rollback 碰运气，也不能重试。
        raise
    output = digest_json({"batch_id": batch_id, "row_count": len(native_rows), "digest": digest})
    return SrcWriteResult(
        dataset=spec.dataset,
        written=True,
        row_count=len(native_rows),
        payload_digest=digest,
        output_digest=output,
        dml_count=2,
        batch_id=batch_id,
        hashes=hashes,
    )


def _rollback_or_unknown(store: SrcWriteStore) -> None:
    store.rollback()


def require_native_rows(
    spec: SrcTableWriteSpec,
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    expected = set(spec.native_columns)
    native: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        payload = {key: value for key, value in row.items() if key not in _TECH_COLUMNS}
        extra = set(payload) - expected
        missing = expected - set(payload)
        if extra or missing:
            raise IngestError(
                f"{spec.dataset} 第 {index} 行列不匹配 extra={sorted(extra)} missing={sorted(missing)}"
            )
        native.append({column: payload[column] for column in spec.native_columns})
    return native


def reject_duplicate_payload_keys(
    spec: SrcTableWriteSpec,
    rows: Sequence[Mapping[str, object]],
) -> None:
    seen: set[tuple[object, ...]] = set()
    for row in rows:
        key = tuple(row[name] for name in spec.keys)
        if key in seen:
            raise DuplicateKeyError(f"{spec.dataset} 载荷内主键重复: {key!r}")
        seen.add(key)


def _sort_token(value: object) -> tuple[int, str]:
    if value is None:
        return (0, "")
    return (1, str(value))
