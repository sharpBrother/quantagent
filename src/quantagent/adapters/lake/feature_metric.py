"""``feature.metric`` 的 Parquet 读取。PIT 截止列来自 domain.pit。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.adapters.lake.convert import as_date, as_datetime, require_float
from quantagent.adapters.lake.visibility import load_dataset_visibility
from quantagent.contracts.loader import load_bundle
from quantagent.contracts.pandera_schema import to_pandera
from quantagent.domain.errors import EmptyDomainError
from quantagent.domain.feature_metric import FeatureMetric
from quantagent.domain.pit import pit_cutoff
from quantagent.domain.query import require_text, require_window
from quantagent.platform.duck import assert_ident, duck_session, register_parquet

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date
    from pathlib import Path

    from quantagent.contracts.spec import VisibilityContract

DATASET = "feature.metric"
_VIEW = "feature_metric"

# DuckDB 把 window 当保留字；列名必须加引号，不是另起字段。
_SQL = """
SELECT event_dt, feature_id, definition_version, param_hash, universe_id,
       horizon, metric_id, "window", benchmark_id, value, knowledge_dt,
       pit_grade, computed_at, run_id
FROM {view}
WHERE feature_id = $feature_id
  AND definition_version = $definition_version
  AND param_hash = $param_hash
  AND universe_id = $universe_id
  AND horizon = $horizon
  AND metric_id = $metric_id
  AND "window" = $window
  AND benchmark_id = $benchmark_id
  AND event_dt BETWEEN $start AND $end
  AND {visibility_column} <= $visible_on_or_before
ORDER BY event_dt
"""


class LakeFeatureMetricRepository:
    """as_of=T 看不到 event_dt=T 的长窗口 IC：那是尚未实现的前瞻收益。"""

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
                    "metric_id": metric_id,
                    "window": window,
                    "benchmark_id": benchmark_id,
                    "start": start,
                    "end": end,
                    "visible_on_or_before": cutoff.on_or_before,
                },
            ).df()
        if frame.empty:
            raise EmptyDomainError(
                f"因子指标为空: metric_id={metric_id} start={start.isoformat()} "
                f"end={end.isoformat()} as_of={as_of.isoformat()}"
            )
        to_pandera(load_bundle().schemas[DATASET]).validate(frame)
        return tuple(_row_from_raw(raw) for raw in frame.to_dict(orient="records"))


def _row_from_raw(raw: Mapping[object, object]) -> FeatureMetric:
    return FeatureMetric(
        event_dt=as_date(raw["event_dt"]),
        feature_id=str(raw["feature_id"]),
        definition_version=str(raw["definition_version"]),
        param_hash=str(raw["param_hash"]),
        universe_id=str(raw["universe_id"]),
        horizon=str(raw["horizon"]),
        metric_id=str(raw["metric_id"]),
        window=str(raw["window"]),
        benchmark_id=str(raw["benchmark_id"]),
        value=require_float(raw["value"]),
        knowledge_dt=as_date(raw["knowledge_dt"]),
        pit_grade=str(raw["pit_grade"]),
        computed_at=as_datetime(raw["computed_at"]),
        run_id=str(raw["run_id"]),
    )
