"""按 PitCutoff.column 从领域行取可见日。"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from quantagent.domain.errors import InvalidQueryError

if TYPE_CHECKING:
    from quantagent.domain.pit import PitCutoff


def row_cutoff_date(row: object, cutoff: PitCutoff) -> date:
    try:
        raw = getattr(row, cutoff.column)
    except AttributeError as exc:
        raise InvalidQueryError(f"行缺少可见性列 {cutoff.column}") from exc
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    raise InvalidQueryError(f"{cutoff.column} 无法转为 date: {raw!r}")
