"""``mart.universe_member`` 行。形状与契约对齐。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date


@dataclass(frozen=True)
class UniverseMember:
    universe_id: str
    asset_id: str
    valid_from: date
    valid_to: date | None
    member_weight: float | None
    knowledge_dt: date
    pit_grade: str
