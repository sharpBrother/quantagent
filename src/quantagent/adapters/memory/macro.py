"""宏观序列的内存实现。截止与版本选择与 PostgreSQL 适配器共用 domain 规则。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.domain.errors import InvalidQueryError, MissingVisibilityError
from quantagent.domain.macro import normalize_series_ids, select_visible_versions
from quantagent.domain.pit import pit_cutoff

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.macro import MacroObservation, MacroVersion


class MemoryMacroRepository:
    def __init__(
        self,
        versions: Sequence[MacroVersion],
        *,
        contracts: Mapping[str, VisibilityContract],
    ) -> None:
        """``contracts`` 按序列 ID 给出该序列所属数据集的可见性契约。"""
        self._versions = tuple(versions)
        self._contracts = dict(contracts)

    def list_observations(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        series_ids: tuple[str, ...],
    ) -> tuple[MacroObservation, ...]:
        ids = normalize_series_ids(series_ids)
        if ids is None:
            return ()
        if start > end:
            raise InvalidQueryError("start 晚于 end")
        out: list[MacroObservation] = []
        for series_id in ids:
            contract = self._contracts.get(series_id)
            if contract is None:
                raise MissingVisibilityError(series_id)
            cutoff = pit_cutoff(contract, as_of=as_of)
            out.extend(
                select_visible_versions(
                    (v for v in self._versions if v.series_id == series_id),
                    start=start,
                    end=end,
                    visible_on_or_before=cutoff.on_or_before,
                    pit_grade=cutoff.grade,
                )
            )
        return tuple(sorted(out, key=lambda row: (row.series_id, row.observation_date)))
