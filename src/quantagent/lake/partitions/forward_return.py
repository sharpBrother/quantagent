"""``mart.forward_return`` 的物理布局与分区写入。

与 ``feature.value`` 的布局相互独立，不改 ``FeatureValueLayout``。分区按 ``event_dt``
年月切成 ``ym=YYYYMM``，与因子长表一致，便于按信号月裁剪。分区列从文件内去掉，留给目录名。

默认不覆盖既有身份。身份键是 ``(asset_id, event_dt, horizon, return_kind,
benchmark_id, return_leg)``：批次内重复或与既有文件重复，都在第一个文件写入之前整批拒绝，
拒绝时不创建任何目录。写后立即回读行数，不一致则删除本次写出的文件。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from quantagent.lake.partitions.layout import LakeLayoutError

if TYPE_CHECKING:
    from pathlib import Path

PARTITION_COLUMN = "ym"
IDENTITY_KEYS: tuple[str, ...] = (
    "asset_id",
    "event_dt",
    "horizon",
    "return_kind",
    "benchmark_id",
    "return_leg",
)
_SORT_KEYS: tuple[str, ...] = ("event_dt", "asset_id", "horizon", "return_leg")
_MAX_ROWS_PER_FILE = 2_000_000


@dataclass(frozen=True)
class ForwardReturnLayout:
    name: str
    compression: str = "zstd"
    row_group_rows: int = 131072

    def validate(self) -> None:
        if self.compression not in {"zstd", "snappy"}:
            raise LakeLayoutError(f"不支持的压缩: {self.compression}")
        if self.row_group_rows < 1:
            raise LakeLayoutError("row_group_rows 必须 >= 1")


FROZEN_FORWARD_RETURN_LAYOUT = ForwardReturnLayout(name="ym_sort_event_zstd")


def write_forward_return_parquet(
    table: pa.Table,
    dest: Path,
    layout: ForwardReturnLayout = FROZEN_FORWARD_RETURN_LAYOUT,
) -> list[Path]:
    """写入 ``dest/ym=YYYYMM/part-NNNNN.parquet``。返回本次新写出的文件。"""
    layout.validate()
    if table.num_rows == 0:
        raise LakeLayoutError("空表拒绝写入")
    missing = [key for key in (*IDENTITY_KEYS, "event_dt") if key not in table.column_names]
    if missing:
        raise LakeLayoutError(f"表缺少身份列: {missing}")
    _refuse_batch_duplicates(table)
    work = table.append_column(
        PARTITION_COLUMN,
        pc.strftime(table["event_dt"], format="%Y%m"),
    )
    plans: list[tuple[pa.Table, Path]] = []
    for ym in sorted(set(work[PARTITION_COLUMN].to_pylist())):
        chunk = work.filter(pc.equal(work[PARTITION_COLUMN], ym)).drop([PARTITION_COLUMN])
        plans.append((chunk, dest / f"{PARTITION_COLUMN}={ym}"))
    # 先检查全部分区，再写任何文件。否则第二个分区冲突时，第一个分区已经写了一半。
    for chunk, part_dir in plans:
        _refuse_existing_identities(chunk, part_dir)
    written: list[Path] = []
    for chunk, part_dir in plans:
        written.extend(_write_sorted_parts(chunk, part_dir, layout))
    return written


def _refuse_batch_duplicates(table: pa.Table) -> None:
    seen: set[tuple[object, ...]] = set()
    for values in _identity_rows(table):
        if values in seen:
            raise LakeLayoutError(f"写入批次含重复身份键: {values}")
        seen.add(values)


def _refuse_existing_identities(chunk: pa.Table, part_dir: Path) -> None:
    files = _part_files(part_dir)
    if not files:
        return
    existing: set[tuple[object, ...]] = set()
    for path in files:
        table = pq.read_table(path, columns=list(IDENTITY_KEYS))
        existing.update(_identity_rows(table))
    overlap = [values for values in _identity_rows(chunk) if values in existing]
    if overlap:
        raise LakeLayoutError(
            f"拒绝覆盖既有行: {part_dir}，重复 {len(overlap)} 行，例如 {overlap[0]}"
        )


def _identity_rows(table: pa.Table) -> list[tuple[object, ...]]:
    columns = [table[key].to_pylist() for key in IDENTITY_KEYS]
    return list(zip(*columns, strict=True))


def _part_files(part_dir: Path) -> list[Path]:
    if not part_dir.is_dir():
        return []
    return sorted(path for path in part_dir.glob("part-*.parquet") if path.is_file())


def _write_sorted_parts(
    chunk: pa.Table,
    part_dir: Path,
    layout: ForwardReturnLayout,
) -> list[Path]:
    ordered = chunk.sort_by([(key, "ascending") for key in _SORT_KEYS])
    part_dir.mkdir(parents=True, exist_ok=True)
    existing = _part_files(part_dir)
    next_no = int(existing[-1].stem.split("-")[-1]) + 1 if existing else 0
    written: list[Path] = []
    offset = 0
    while offset < ordered.num_rows:
        piece = ordered.slice(offset, _MAX_ROWS_PER_FILE)
        path = part_dir / f"part-{next_no:05d}.parquet"
        if path.exists():
            raise LakeLayoutError(f"拒绝覆盖既有文件: {path}")
        pq.write_table(
            piece,
            path,
            compression=layout.compression,
            compression_level=3 if layout.compression == "zstd" else None,
            write_statistics=True,
            row_group_size=layout.row_group_rows,
        )
        written.append(path)
        next_no += 1
        offset += piece.num_rows
    return written
