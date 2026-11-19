"""源镜像跟随源端：不带源端版本身份的表（Tushare ``shibor`` 等）。

判定规则见 docs/adr/2026-11-18-tushare-mirror-follows-source.md，与 Wind 一致：

- 目标键不存在：插入，计入 ``inserted``。
- 指纹相同：跳过，计入 ``skipped``。
- 指纹不同：逐列比较业务列。全部相等计入 ``metadata_skipped`` 且不写库；有差异则同一事务内
  按主键删旧插新，计入 ``replaced``。
- 源端没返回的已写行不删。Tushare 没有删除标记，接口缺行不等于源端删除。

``_row_hash`` 只对主键和业务列计算，不含 ``source`` 与 ``ingested_at``。这两列每次采集都会变，
若算进指纹，同一份数据每次采集都会被当成变化。

每次写入（包括没有任何行变化的写入）都会登记一条 ``_batch``。日更起点靠最近成功批次的
``window_end`` 推出，所以无变化的日更也必须留下批次行。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import psycopg

from quantagent.adapters.postgres.errors import SrcConflictError, TransactionUnknownError
from quantagent.ingest.errors import (
    DuplicateKeyError,
    EmptyPayloadError,
    IngestError,
    ReadbackError,
)
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

# 系统列：来源标记与采集时刻。不参与指纹，也不参与业务比较。
_SYSTEM_COLUMNS: frozenset[str] = frozenset({"source", "ingested_at"})

# 诊断信息里最多列几个样例。
_SAMPLE = 5


@dataclass(frozen=True)
class SrcFollowWriteResult:
    """``written`` 为 False 时是干跑：只算了 ``row_count`` 与 digest，计数字段均为 0，不代表没有变化。"""

    dataset: str
    written: bool
    row_count: int
    inserted: int
    replaced: int
    skipped: int
    metadata_skipped: int
    payload_digest: str
    output_digest: str
    dml_count: int
    batch_id: int | None


@dataclass(frozen=True)
class _Plan:
    insert_rows: tuple[Mapping[str, object], ...]
    insert_hashes: tuple[str, ...]
    insert_keys: tuple[tuple[object, ...], ...]
    delete_keys: tuple[tuple[object, ...], ...]
    inserted: int
    replaced: int
    skipped: int
    metadata_skipped: int


def business_columns(spec: SrcTableWriteSpec) -> tuple[str, ...]:
    """业务列：原生列去掉主键与系统列。"""
    return tuple(
        name
        for name in spec.native_columns
        if name not in _SYSTEM_COLUMNS and name not in spec.keys
    )


def fingerprint_columns(spec: SrcTableWriteSpec) -> tuple[str, ...]:
    """指纹覆盖的列：主键加业务列。系统列不在其中，原因见模块文档。"""
    return (*spec.keys, *business_columns(spec))


def write_src_follow(
    *,
    spec: SrcTableWriteSpec,
    rows: Sequence[Mapping[str, object]],
    settings: Settings,
    write_db: bool,
    store: SrcWriteStore | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    now: Callable[[], datetime] | None = None,
) -> SrcFollowWriteResult:
    """``write_db`` 默认由调用方传 False。真写必须同时打开环境写闸。

    ``now`` 必须返回带时区的 UTC 时刻。表有原生 ``ingested_at`` 列时，行里的值必须是同一时刻去掉时区后的值，
    这样原生列与 ``_ingested_at`` 指向同一次采集。没有该列的表只靠 ``_ingested_at``。
    """
    assert_writable(spec, profile=settings.profile)
    native_rows = require_native_rows(spec, rows)
    if not native_rows:
        raise EmptyPayloadError(f"{spec.dataset} 载荷为空")
    reject_duplicate_payload_keys(spec, native_rows)

    fingerprint = fingerprint_columns(spec)
    keys = [tuple(row[name] for name in spec.keys) for row in native_rows]
    hashes = [row_hash(row, fingerprint) for row in native_rows]
    digest = payload_digest(native_rows, fingerprint)

    if not write_db:
        return SrcFollowWriteResult(
            dataset=spec.dataset,
            written=False,
            row_count=len(native_rows),
            inserted=0,
            replaced=0,
            skipped=0,
            metadata_skipped=0,
            payload_digest=digest,
            output_digest=digest,
            dml_count=0,
            batch_id=None,
        )

    assert_db_write_allowed(settings=settings, write_db=True)
    if store is None:
        raise IngestError("write_db 为真时必须提供 SrcWriteStore")

    clock = now or (lambda: datetime.now(UTC))
    started_at = clock()
    finished_at = clock()
    # 只有表里真有原生 ingested_at 列时才核对行内值。0018 起的新表不再建冗余的原生 ingested_at 列，
    # 这类表（GPR、FRED）的采集时刻只通过 _ingested_at 落库，行内不带它。
    if "ingested_at" in spec.native_columns:
        expected_ingested = finished_at.astimezone(UTC).replace(tzinfo=None)
        if any(row["ingested_at"] != expected_ingested for row in native_rows):
            raise IngestError(f"{spec.dataset} 行的 ingested_at 与本次采集时刻不一致")

    plan = _plan(spec, store, native_rows, keys, hashes)
    batch_id = store.insert_batch(
        spec=spec,
        window_start=window_start,
        window_end=window_end,
        row_count=len(native_rows),
        payload_digest=digest,
        started_at=started_at,
        finished_at=finished_at,
    )
    dml_count = _apply(spec, store, plan, batch_id=batch_id, ingested_at=finished_at)
    _verify(spec, store, plan, batch_id=batch_id)
    try:
        store.commit()
    except TransactionUnknownError:
        # 提交结果不确定时停下报告，不重试、不回滚碰运气。
        raise

    output = digest_json({"batch_id": batch_id, "row_count": len(native_rows), "digest": digest})
    return SrcFollowWriteResult(
        dataset=spec.dataset,
        written=True,
        row_count=len(native_rows),
        inserted=plan.inserted,
        replaced=plan.replaced,
        skipped=plan.skipped,
        metadata_skipped=plan.metadata_skipped,
        payload_digest=digest,
        output_digest=output,
        dml_count=dml_count,
        batch_id=batch_id,
    )


def _plan(
    spec: SrcTableWriteSpec,
    store: SrcWriteStore,
    native_rows: Sequence[Mapping[str, object]],
    keys: Sequence[tuple[object, ...]],
    hashes: Sequence[str],
) -> _Plan:
    """读库里的已有指纹，逐行决定插入、跳过、替换或元数据跳过。只读，不写库。"""
    business = business_columns(spec)
    try:
        existing = store.existing_hashes(spec, keys)
    except psycopg.errors.DataError as exc:
        store.rollback()
        raise IngestError(f"{spec.dataset} 查询已有指纹时参数被 PG 拒收: {exc}") from exc

    # 只有指纹变了的键才需要读库里的业务列；绝大多数键指纹相同，不必逐列读。
    changed = [
        key
        for key, row_digest in zip(keys, hashes, strict=True)
        if key in existing and existing[key] != row_digest
    ]
    stored = store.existing_values(spec, changed, business) if changed else {}

    insert_rows: list[Mapping[str, object]] = []
    insert_hashes: list[str] = []
    insert_keys: list[tuple[object, ...]] = []
    delete_keys: list[tuple[object, ...]] = []
    inserted = 0
    replaced = 0
    skipped = 0
    metadata_skipped = 0
    for row, key, row_digest in zip(native_rows, keys, hashes, strict=True):
        current = existing.get(key)
        if current is None:
            insert_rows.append(row)
            insert_hashes.append(row_digest)
            insert_keys.append(key)
            inserted += 1
            continue
        if current == row_digest:
            skipped += 1
            continue
        values = stored.get(key)
        # 逐列用 == 比较而不是重算指纹：库里 numeric 读回的 Decimal 标度可能与源端不同，
        # == 按数值比较，不会把 10.5 与 10.5000 误判为变化。
        if values is not None and all(
            row[name] == value for name, value in zip(business, values, strict=True)
        ):
            metadata_skipped += 1
            continue
        delete_keys.append(key)
        insert_rows.append(row)
        insert_hashes.append(row_digest)
        insert_keys.append(key)
        replaced += 1
    return _Plan(
        insert_rows=tuple(insert_rows),
        insert_hashes=tuple(insert_hashes),
        insert_keys=tuple(insert_keys),
        delete_keys=tuple(delete_keys),
        inserted=inserted,
        replaced=replaced,
        skipped=skipped,
        metadata_skipped=metadata_skipped,
    )


def _apply(
    spec: SrcTableWriteSpec,
    store: SrcWriteStore,
    plan: _Plan,
    *,
    batch_id: int,
    ingested_at: datetime,
) -> int:
    """同一事务内先删后插。返回本次写入的 DML 条数，含批次登记。失败时回滚。"""
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
        store.rollback()
        raise DuplicateKeyError(f"{spec.dataset} 插入时撞上已有键，已回滚") from exc
    except psycopg.errors.DataError as exc:
        store.rollback()
        raise IngestError(f"{spec.dataset} 参数被 PG 拒收，已回滚: {exc}") from exc
    return dml_count


def _verify(
    spec: SrcTableWriteSpec,
    store: SrcWriteStore,
    plan: _Plan,
    *,
    batch_id: int,
) -> None:
    """先比指纹，再逐列比。任一不一致都回滚并抛 ``ReadbackError``。"""
    readback = store.readback_hashes(spec, batch_id, plan.insert_keys)
    if len(readback) != len(plan.insert_hashes) or sorted(readback) != sorted(plan.insert_hashes):
        store.rollback()
        raise ReadbackError(
            f"{spec.dataset} 回读不一致：wrote={len(plan.insert_hashes)} read={len(readback)} "
            f"inserted={plan.inserted} replaced={plan.replaced}"
        )
    # 指纹一致之后再逐列核对。指纹是客户端算好随行发上去的，只比指纹挡不住业务列被改坏。
    mismatched = store.mismatched_rows(spec, batch_id, plan.insert_rows)
    if mismatched:
        store.rollback()
        raise ReadbackError(
            f"{spec.dataset} 回读逐列核对不一致 {len(mismatched)} 行，已回滚；"
            f"样例 {mismatched[:_SAMPLE]!r}"
        )
