"""``signal.group_nav`` 行。形状与契约对齐；可见日是 knowledge_dt，不是 event_dt。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date


@dataclass(frozen=True)
class GroupNav:
    event_dt: date
    feature_id: str
    definition_version: str
    param_hash: str
    universe_id: str
    horizon: str
    group_no: int
    group_return: float
    group_nav: float
    knowledge_dt: date
    pit_grade: str
    pit_report: str
    run_id: str
    code_version: str
    config_digest: str
