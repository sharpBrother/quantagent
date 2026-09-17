"""因子长表物理布局。

分区键、排序键、压缩以 ADR
``docs/adr/2026-09-17-feature-value-parquet-layout.md`` 为准。
``feature_id`` 进分区键会把全 A × 因子数打成 KB 级小文件，这里直接拒绝。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Compression = Literal["zstd", "snappy"]

ALLOWED_PARTITION_KEYS = frozenset({"event_dt", "ym", "year", "asset_class"})
FORBIDDEN_PARTITION_KEYS = frozenset({"feature_id", "definition_version", "param_hash"})
ALLOWED_SORT_KEYS = (
    "event_dt",
    "asset_id",
    "feature_id",
    "definition_version",
    "param_hash",
    "asset_class",
)
TARGET_FILE_MB_MIN = 64
TARGET_FILE_MB_MAX = 512


class LakeLayoutError(Exception):
    """物理布局非法，或试图覆盖既有 parquet 分区。"""


@dataclass(frozen=True)
class FeatureValueLayout:
    name: str
    partition_keys: tuple[str, ...]
    sort_keys: tuple[str, ...]
    compression: Compression
    target_file_mb: int = 128
    row_group_rows: int = 131072

    def validate(self) -> None:
        if self.compression not in {"zstd", "snappy"}:
            raise LakeLayoutError(f"不支持的压缩: {self.compression}")
        if self.target_file_mb < TARGET_FILE_MB_MIN or self.target_file_mb > TARGET_FILE_MB_MAX:
            raise LakeLayoutError(
                f"目标文件大小必须落在 {TARGET_FILE_MB_MIN}–{TARGET_FILE_MB_MAX}MB"
            )
        if self.row_group_rows < 1:
            raise LakeLayoutError("row_group_rows 必须 >= 1")
        seen: set[str] = set()
        for key in self.partition_keys:
            if key in FORBIDDEN_PARTITION_KEYS:
                raise LakeLayoutError(f"禁止把 {key} 当作分区键：会碎成不可扫描的小文件")
            if key not in ALLOWED_PARTITION_KEYS:
                raise LakeLayoutError(f"未知分区键: {key}")
            if key in seen:
                raise LakeLayoutError(f"重复分区键: {key}")
            seen.add(key)
        if not self.sort_keys:
            raise LakeLayoutError("排序键不能为空")
        for key in self.sort_keys:
            if key not in ALLOWED_SORT_KEYS:
                raise LakeLayoutError(f"未知排序键: {key}")


# 由 benchmark 结论冻结。改这一处必须同步改 ADR 的 supersede，而不是静默换布局。
FROZEN_FEATURE_VALUE_LAYOUT = FeatureValueLayout(
    name="asset_class_ym_sort_event_zstd",
    partition_keys=("asset_class", "ym"),
    sort_keys=("event_dt", "asset_id", "feature_id", "definition_version", "param_hash"),
    compression="zstd",
    target_file_mb=128,
    row_group_rows=131072,
)
