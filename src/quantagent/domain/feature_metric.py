"""``feature.metric`` 行。形状与契约对齐；可见日是 knowledge_dt，不是 event_dt。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime


@dataclass(frozen=True)
class FeatureMetric:
    event_dt: date
    feature_id: str
    definition_version: str
    param_hash: str
    universe_id: str
    horizon: str
    metric_id: str
    window: str
    benchmark_id: str
    value: float
    knowledge_dt: date
    pit_grade: str
    computed_at: datetime
    run_id: str
