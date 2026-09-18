"""``feature.metric`` 的内存实现。与 lake 适配器跑同一套契约测试。"""

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
    from quantagent.domain.feature_metric import FeatureMetric


class MemoryFeatureMetricRepository:
    def __init__(self, rows: Sequence[FeatureMetric], *, contract: VisibilityContract) -> None:
        self._rows = tuple(rows)
        self._contract = contract

    def scan_window(
        self,
        *,
        as_of: date,
        feature_id: str,
        definition_version: str,
        param_hash: str,
        universe_id: str,
        horizon: str,
        metric_id: str,
        window: str,
        benchmark_id: str,
        start: date,
        end: date,
    ) -> tuple[FeatureMetric, ...]:
        require_text(
            feature_id,
            definition_version,
            param_hash,
            universe_id,
            horizon,
            metric_id,
            window,
            benchmark_id,
        )
        require_window(start, end)
        cutoff = pit_cutoff(self._contract, as_of=as_of)
        matched = [
            row
            for row in self._rows
            if row.feature_id == feature_id
            and row.definition_version == definition_version
            and row.param_hash == param_hash
            and row.universe_id == universe_id
            and row.horizon == horizon
            and row.metric_id == metric_id
            and row.window == window
            and row.benchmark_id == benchmark_id
            and start <= row.event_dt <= end
            and is_cutoff_visible(value=row_cutoff_date(row, cutoff), cutoff=cutoff)
        ]
        if not matched:
            raise EmptyDomainError(
                f"因子指标为空: metric_id={metric_id} start={start.isoformat()} "
                f"end={end.isoformat()} as_of={as_of.isoformat()}"
            )
        return tuple(sorted(matched, key=lambda row: row.event_dt))
