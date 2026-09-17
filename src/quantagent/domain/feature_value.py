"""``feature.value`` 长表行与训练宽表行。形状与契约对齐，不含存储字段。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
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
