"""``signal.group_nav`` 的 Parquet 读取。PIT 截止列来自 domain.pit。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.adapters.lake.convert import as_date, as_int, require_float
from quantagent.adapters.lake.visibility import load_dataset_visibility
from quantagent.contracts.loader import load_bundle
from quantagent.contracts.pandera_schema import to_pandera
from quantagent.domain.errors import EmptyDomainError
from quantagent.domain.group_nav import GroupNav
from quantagent.domain.pit import pit_cutoff
from quantagent.domain.query import require_text, require_window
from quantagent.platform.duck import assert_ident, duck_session, register_parquet

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date
    from pathlib import Path

    from quantagent.contracts.spec import VisibilityContract

DATASET = "signal.group_nav"
_VIEW = "group_nav"

_SQL = """
SELECT event_dt, feature_id, definition_version, param_hash, universe_id,
       horizon, group_no, group_return, group_nav, knowledge_dt, pit_grade,
       pit_report, run_id, code_version, config_digest
FROM {view}
WHERE feature_id = $feature_id
  AND definition_version = $definition_version
  AND param_hash = $param_hash
  AND universe_id = $universe_id
  AND horizon = $horizon
  AND run_id = $run_id
  AND event_dt BETWEEN $start AND $end
  AND {visibility_column} <= $visible_on_or_before
ORDER BY event_dt, group_no
"""


class LakeGroupNavRepository:
    """分组净值含前瞻窗口，可见日不是净值日 event_dt。"""

    def __init__(self, source: Path, *, contract: VisibilityContract | None = None) -> None:
        self._source = source
        self._contract = contract if contract is not None else load_dataset_visibility(DATASET)

    def scan_window(
        self,
        *,
        as_of: date,
        feature_id: str,
        definition_version: str,
        param_hash: str,
        universe_id: str,
        horizon: str,
        run_id: str,
        start: date,
        end: date,
    ) -> tuple[GroupNav, ...]:
        require_text(feature_id, definition_version, param_hash, universe_id, horizon, run_id)
        require_window(start, end)
        cutoff = pit_cutoff(self._contract, as_of=as_of)
        with duck_session() as conn:
            register_parquet(conn, _VIEW, self._source)
            frame = conn.execute(
                _SQL.format(
                    view=assert_ident(_VIEW), visibility_column=assert_ident(cutoff.column)
                ),
                {
                    "feature_id": feature_id,
                    "definition_version": definition_version,
                    "param_hash": param_hash,
                    "universe_id": universe_id,
                    "horizon": horizon,
                    "run_id": run_id,
                    "start": start,
                    "end": end,
                    "visible_on_or_before": cutoff.on_or_before,
                },
            ).df()
        if frame.empty:
            raise EmptyDomainError(
                f"分组净值为空: run_id={run_id} start={start.isoformat()} "
                f"end={end.isoformat()} as_of={as_of.isoformat()}"
            )
        to_pandera(load_bundle().schemas[DATASET]).validate(frame)
        return tuple(_row_from_raw(raw) for raw in frame.to_dict(orient="records"))


def _row_from_raw(raw: Mapping[object, object]) -> GroupNav:
    return GroupNav(
        event_dt=as_date(raw["event_dt"]),
        feature_id=str(raw["feature_id"]),
        definition_version=str(raw["definition_version"]),
        param_hash=str(raw["param_hash"]),
        universe_id=str(raw["universe_id"]),
        horizon=str(raw["horizon"]),
        group_no=as_int(raw["group_no"]),
        group_return=require_float(raw["group_return"]),
        group_nav=require_float(raw["group_nav"]),
        knowledge_dt=as_date(raw["knowledge_dt"]),
        pit_grade=str(raw["pit_grade"]),
        pit_report=str(raw["pit_report"]),
        run_id=str(raw["run_id"]),
        code_version=str(raw["code_version"]),
        config_digest=str(raw["config_digest"]),
    )
