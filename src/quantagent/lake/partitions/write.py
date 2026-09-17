"""按布局把 ``feature.value`` Arrow 表写成 Hive 分区 parquet。

分区列从文件内去掉、留给目录名，这样 DuckDB ``hive_partitioning`` 才能用
查询里的同名谓词做裁剪。默认拒绝覆盖既有文件。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from quantagent.lake.partitions.layout import LakeLayoutError

if TYPE_CHECKING:
    from pathlib import Path

    from quantagent.lake.partitions.layout import FeatureValueLayout

_BYTES_PER_ROW_HINT = 24
WriteMode = Literal["error", "overwrite", "append"]


def write_feature_value_parquet(
    table: pa.Table,
    dest: Path,
    layout: FeatureValueLayout,
    *,
    mode: WriteMode = "error",
) -> dict[str, int]:
    """写入一个布局目录。返回文件数与总字节。"""
    layout.validate()
    if table.num_rows == 0:
        raise LakeLayoutError("空表拒绝写入")
    dest.mkdir(parents=True, exist_ok=True)
    existing = [path for path in dest.rglob("*.parquet") if path.is_file()]
    if existing and mode == "error":
        raise LakeLayoutError(f"拒绝覆盖既有分区: {dest}")
    if existing and mode == "overwrite":
        for path in existing:
            path.unlink()
    table = _decode_dictionaries(table)
    work = _with_partition_columns(table, layout.partition_keys)
    if not layout.partition_keys:
        return _write_sorted_files(
            work,
            dest,
            layout,
            file_sort=layout.sort_keys,
            mode=mode,
        )
    n_files = 0
    nbytes = 0
    groups = work.group_by(list(layout.partition_keys)).aggregate([("value", "count")])
    for i in range(groups.num_rows):
        key_vals = {key: groups[key][i].as_py() for key in layout.partition_keys}
        chunk = work.filter(_partition_mask(work, key_vals)).drop(list(layout.partition_keys))
        part_dir = dest
        for key, value in key_vals.items():
            part_dir = part_dir / f"{key}={_hive_value(value)}"
        file_sort = tuple(key for key in layout.sort_keys if key not in layout.partition_keys)
        written = _write_sorted_files(chunk, part_dir, layout, file_sort=file_sort, mode=mode)
        n_files += written["n_files"]
        nbytes += written["nbytes"]
    return {"n_files": n_files, "nbytes": nbytes}


def _with_partition_columns(table: pa.Table, keys: tuple[str, ...]) -> pa.Table:
    work = table
    if "ym" in keys and "ym" not in work.column_names:
        work = work.append_column("ym", pc.strftime(work["event_dt"], format="%Y%m"))
    if "year" in keys and "year" not in work.column_names:
        work = work.append_column("year", pc.strftime(work["event_dt"], format="%Y"))
    missing = [key for key in keys if key not in work.column_names]
    if missing:
        raise LakeLayoutError(f"表缺少分区列: {missing}")
    return work


def _partition_mask(table: pa.Table, key_vals: dict[str, object]) -> pa.ChunkedArray:
    mask: pa.ChunkedArray | None = None
    for key, value in key_vals.items():
        col = table[key]
        eq = pc.equal(col, pa.scalar(value, type=col.type))
        mask = eq if mask is None else pc.and_(mask, eq)
    if mask is None:
        raise LakeLayoutError("分区键为空却走了分区写入")
    return mask


def _hive_value(value: object) -> str:
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    if any(sep in text for sep in ("/", "\\", "=", "\x00")):
        raise LakeLayoutError(f"分区值含非法字符: {text!r}")
    return text


def _write_sorted_files(
    table: pa.Table,
    dest: Path,
    layout: FeatureValueLayout,
    *,
    file_sort: tuple[str, ...],
    mode: WriteMode,
) -> dict[str, int]:
    if table.num_rows == 0:
        return {"n_files": 0, "nbytes": 0}
    sort_spec = [(key, "ascending") for key in file_sort if key in table.column_names]
    chunk = table.sort_by(sort_spec) if sort_spec else table
    dest.mkdir(parents=True, exist_ok=True)
    max_rows = _max_rows_per_file(layout)
    n_files = 0
    nbytes = 0
    offset = 0
    part = _next_part_index(dest) if mode == "append" else 0
    while offset < chunk.num_rows:
        end = min(offset + max_rows, chunk.num_rows)
        piece = chunk.slice(offset, end - offset)
        path = dest / f"part-{part:05d}.parquet"
        if path.exists():
            raise LakeLayoutError(f"拒绝覆盖既有文件: {path}")
        sorting_columns = [
            pq.SortingColumn(piece.schema.get_field_index(key))
            for key in file_sort
            if key in piece.column_names
        ]
        pq.write_table(
            piece,
            path,
            compression=layout.compression,
            compression_level=3 if layout.compression == "zstd" else None,
            write_statistics=True,
            write_page_index=True,
            use_dictionary=True,
            row_group_size=layout.row_group_rows,
            sorting_columns=sorting_columns or None,
        )
        n_files += 1
        nbytes += path.stat().st_size
        offset = end
        part += 1
    return {"n_files": n_files, "nbytes": nbytes}


def _next_part_index(dest: Path) -> int:
    existing = sorted(dest.glob("part-*.parquet"))
    if not existing:
        return 0
    last = existing[-1].stem.split("-")[-1]
    return int(last) + 1


def _decode_dictionaries(table: pa.Table) -> pa.Table:
    """sort_by 不接受 dictionary 列；写入前解码，parquet 仍会做字典编码。"""
    arrays = []
    for field in table.schema:
        column = table[field.name]
        if pa.types.is_dictionary(field.type):
            arrays.append(column.cast(field.type.value_type))
        else:
            arrays.append(column)
    return pa.Table.from_arrays(arrays, names=table.column_names)


def _max_rows_per_file(layout: FeatureValueLayout) -> int:
    hinted = (layout.target_file_mb * 1024 * 1024) // _BYTES_PER_ROW_HINT
    return max(layout.row_group_rows, hinted)
