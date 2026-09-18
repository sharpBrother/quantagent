"""``mart.universe_member`` 的内存实现。与 lake 适配器跑同一套契约测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.adapters.memory.pit_row import row_cutoff_date
from quantagent.domain.errors import EmptyDomainError
from quantagent.domain.pit import is_cutoff_visible, pit_cutoff
from quantagent.domain.query import require_text
from quantagent.domain.universe import interval_contains

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.universe import UniverseMember


class MemoryUniverseRepository:
    def __init__(self, rows: Sequence[UniverseMember], *, contract: VisibilityContract) -> None:
        self._rows = tuple(rows)
        self._contract = contract

    def members_at(
        self,
        *,
        as_of: date,
        dt: date,
        universe_id: str,
    ) -> tuple[UniverseMember, ...]:
        require_text(universe_id)
        cutoff = pit_cutoff(self._contract, as_of=as_of)
        matched = [
            row
            for row in self._rows
            if row.universe_id == universe_id
            and interval_contains(valid_from=row.valid_from, valid_to=row.valid_to, dt=dt)
            and is_cutoff_visible(value=row_cutoff_date(row, cutoff), cutoff=cutoff)
        ]
        if not matched:
            raise EmptyDomainError(
                f"股票池为空: universe_id={universe_id} dt={dt.isoformat()} "
                f"as_of={as_of.isoformat()}"
            )
        return tuple(sorted(matched, key=lambda row: (row.asset_id, row.valid_from)))
