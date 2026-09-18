"""``feature.value`` 长表行与训练宽表行。形状与契约对齐，不含存储字段。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from quantagent.domain.errors import EmptyDomainError, FeatureLookupError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date, datetime


@dataclass(frozen=True)
class FeatureValue:
    event_dt: date
    asset_id: str
    asset_class: str
    feature_id: str
    definition_version: str
    param_hash: str
    value: float
    knowledge_dt: date
    pit_grade: str
    computed_at: datetime
    run_id: str


@dataclass(frozen=True)
class FeatureMatrixRow:
    asset_id: str
    event_dt: date
    # 缺失因子保持 None，不补 0、不补前值。
    values: Mapping[str, float | None]


@dataclass(frozen=True)
class FeatureKey:
    """矩阵输入必须绑定完整身份，不能按文件顺序选择某个版本。"""

    feature_id: str
    definition_version: str
    param_hash: str


def validate_matrix_features(feature_keys: Sequence[FeatureKey]) -> tuple[FeatureKey, ...]:
    keys = tuple(feature_keys)
    if not keys:
        raise EmptyDomainError("feature_keys 为空，拒绝查询")
    seen: set[str] = set()
    for key in keys:
        if any(
            not value.strip() or "\x00" in value
            for value in (key.feature_id, key.definition_version, key.param_hash)
        ):
            raise FeatureLookupError("因子完整身份不能为空或包含 NUL")
        # 宽表仍以 feature_id 命名，大小写冲突也会被 DuckDB 视作同一列。
        name = key.feature_id.casefold()
        if name in seen or name in {"asset_id", "event_dt"}:
            raise FeatureLookupError(f"矩阵因子列重复或冲突: {key.feature_id}")
        seen.add(name)
    return keys
