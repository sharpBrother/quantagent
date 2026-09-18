"""``mart.forward_return`` 的 Parquet 读取。PIT 截止列来自 domain.pit。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.adapters.lake.convert import as_date, require_float
from quantagent.adapters.lake.visibility import load_dataset_visibility
from quantagent.contracts.loader import load_bundle
from quantagent.contracts.pandera_schema import to_pandera
from quantagent.domain.errors import EmptyDomainError
from quantagent.domain.forward_return import ForwardReturn
from quantagent.domain.pit import pit_cutoff
from quantagent.domain.query import require_text, require_window
from quantagent.platform.duck import assert_ident, duck_session, register_parquet

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date
    from pathlib import Path

    from quantagent.contracts.spec import VisibilityContract

DATASET = "mart.forward_return"
_VIEW = "forward_return"

_SQL = """
SELECT asset_id, event_dt, horizon, return_kind, benchmark_id,
       value, end_dt, knowledge_dt, pit_grade
FROM {view}
WHERE horizon = $horizon
  AND return_kind = $return_kind
  AND benchmark_id = $benchmark_id
  AND event_dt BETWEEN $start AND $end
  AND {visibility_column} <= $visible_on_or_before
ORDER BY asset_id, event_dt
"""


class LakeForwardReturnRepository:
    """不用 event_dt 做可见性：那是前瞻区间起点，收益在 end_dt 才实现。"""

    def __init__(self, source: Path, *, contract: VisibilityContract | None = None) -> None:
        self._source = source
        self._contract = contract if contract is not None else load_dataset_visibility(DATASET)

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
        with duck_session() as conn:
            register_parquet(conn, _VIEW, self._source)
            frame = conn.execute(
                _SQL.format(
                    view=assert_ident(_VIEW), visibility_column=assert_ident(cutoff.column)
                ),
                {
                    "horizon": horizon,
                    "return_kind": return_kind,
                    "benchmark_id": benchmark_id,
                    "start": start,
                    "end": end,
                    "visible_on_or_before": cutoff.on_or_before,
                },
            ).df()
        if frame.empty:
            raise EmptyDomainError(
                f"前瞻收益为空: horizon={horizon} start={start.isoformat()} "
                f"end={end.isoformat()} as_of={as_of.isoformat()}"
            )
        to_pandera(load_bundle().schemas[DATASET]).validate(frame)
        return tuple(_row_from_raw(raw) for raw in frame.to_dict(orient="records"))


def _row_from_raw(raw: Mapping[object, object]) -> ForwardReturn:
    return ForwardReturn(
        asset_id=str(raw["asset_id"]),
        event_dt=as_date(raw["event_dt"]),
        horizon=str(raw["horizon"]),
        return_kind=str(raw["return_kind"]),
        benchmark_id=str(raw["benchmark_id"]),
        value=require_float(raw["value"]),
        end_dt=as_date(raw["end_dt"]),
        knowledge_dt=as_date(raw["knowledge_dt"]),
        pit_grade=str(raw["pit_grade"]),
    )
