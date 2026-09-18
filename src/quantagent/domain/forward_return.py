"""``mart.forward_return`` 行。形状与契约对齐；可见日是 knowledge_dt，不是 event_dt。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date


@dataclass(frozen=True)
class ForwardReturn:
    asset_id: str
    event_dt: date
    horizon: str
    return_kind: str
    benchmark_id: str
    value: float
    end_dt: date
    knowledge_dt: date
    pit_grade: str
