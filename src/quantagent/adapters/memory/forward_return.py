"""``mart.forward_return`` 的内存实现。与 lake 适配器跑同一套契约测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.adapters.memory.pit_row import row_cutoff_date
from quantagent.domain.errors import EmptyDomainError
from quantagent.domain.pit import is_cutoff_visible, pit_cutoff
from quantagent.domain.query import require_text, require_window

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.forward_return import ForwardReturn


class MemoryForwardReturnRepository:
    def __init__(self, rows: Sequence[ForwardReturn], *, contract: VisibilityContract) -> None:
        self._rows = tuple(rows)
        self._contract = contract

    def scan_window(
        self,
        *,
        as_of: date,
        horizon: str,
        return_kind: str,
        benchmark_id: str,
        start: date,
        end: date,
    ) -> tuple[ForwardReturn, ...]:
        require_text(horizon, return_kind, benchmark_id)
        require_window(start, end)
        cutoff = pit_cutoff(self._contract, as_of=as_of)
        matched = [
            row
            for row in self._rows
            if row.horizon == horizon
            and row.return_kind == return_kind
            and row.benchmark_id == benchmark_id
            and start <= row.event_dt <= end
            and is_cutoff_visible(value=row_cutoff_date(row, cutoff), cutoff=cutoff)
        ]
        if not matched:
            raise EmptyDomainError(
                f"前瞻收益为空: horizon={horizon} start={start.isoformat()} "
                f"end={end.isoformat()} as_of={as_of.isoformat()}"
            )
        return tuple(sorted(matched, key=lambda row: (row.asset_id, row.event_dt)))
