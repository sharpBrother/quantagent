from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SignalPack:
    symbol: str
    as_of: str
    indicators: dict[str, float | None]
    labels: dict[str, str]
    bar_count: int = 0
    source: str = "fixture"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnalysisBrief:
    summary: str
    research_steps: list[str]
    risks: list[str]
    disclaimer: str
    mode: str
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DISCLAIMER = (
    "Not investment advice. Educational analysis only. "
    "Past indicator patterns do not guarantee future results."
)
