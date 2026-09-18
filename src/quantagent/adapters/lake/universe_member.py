"""``mart.universe_member`` 的 Parquet 读取。PIT 截止列来自 domain.pit。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.adapters.lake.convert import as_date, as_optional_date, optional_float
from quantagent.adapters.lake.visibility import load_dataset_visibility
from quantagent.contracts.loader import load_bundle
from quantagent.contracts.pandera_schema import to_pandera
from quantagent.domain.errors import EmptyDomainError
from quantagent.domain.pit import pit_cutoff
from quantagent.domain.query import require_text
from quantagent.domain.universe import UniverseMember
from quantagent.platform.duck import assert_ident, duck_session, register_parquet

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date
    from pathlib import Path

    from quantagent.contracts.spec import VisibilityContract

DATASET = "mart.universe_member"
_VIEW = "universe_member"

# 闭区间与 domain.universe.interval_contains 同一口径；SQL 不得另写半开。
_SQL = """
SELECT universe_id, asset_id, valid_from, valid_to, member_weight,
       knowledge_dt, pit_grade
FROM {view}
WHERE universe_id = $universe_id
  AND valid_from <= $dt
  AND (valid_to IS NULL OR valid_to >= $dt)
  AND {visibility_column} <= $visible_on_or_before
ORDER BY asset_id, valid_from
"""


class LakeUniverseRepository:
    """成员查询必须同时区间命中和可见日截止，不能只滤 knowledge_dt。"""

    def __init__(self, source: Path, *, contract: VisibilityContract | None = None) -> None:
        self._source = source
        self._contract = contract if contract is not None else load_dataset_visibility(DATASET)

    def members_at(
        self,
        *,
        as_of: date,
        dt: date,
        universe_id: str,
    ) -> tuple[UniverseMember, ...]:
        require_text(universe_id)
        cutoff = pit_cutoff(self._contract, as_of=as_of)
        with duck_session() as conn:
            register_parquet(conn, _VIEW, self._source)
            frame = conn.execute(
                _SQL.format(
                    view=assert_ident(_VIEW), visibility_column=assert_ident(cutoff.column)
                ),
                {
                    "universe_id": universe_id,
                    "dt": dt,
                    "visible_on_or_before": cutoff.on_or_before,
                },
            ).df()
        if frame.empty:
            raise EmptyDomainError(
                f"股票池为空: universe_id={universe_id} dt={dt.isoformat()} "
                f"as_of={as_of.isoformat()}"
            )
        to_pandera(load_bundle().schemas[DATASET]).validate(frame)
        return tuple(_row_from_raw(raw) for raw in frame.to_dict(orient="records"))


def _row_from_raw(raw: Mapping[object, object]) -> UniverseMember:
    return UniverseMember(
        universe_id=str(raw["universe_id"]),
        asset_id=str(raw["asset_id"]),
        valid_from=as_date(raw["valid_from"]),
        valid_to=as_optional_date(raw["valid_to"]),
        member_weight=optional_float(raw["member_weight"]),
        knowledge_dt=as_date(raw["knowledge_dt"]),
        pit_grade=str(raw["pit_grade"]),
    )
