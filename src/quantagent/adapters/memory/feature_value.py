"""``feature.value`` 的内存实现。与 lake 适配器跑同一套契约测试。"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from quantagent.domain.errors import EmptyDomainError, FeatureLookupError
from quantagent.domain.feature_value import FeatureMatrixRow, FeatureValue
from quantagent.domain.pit import is_cutoff_visible, pit_cutoff

if TYPE_CHECKING:
    from collections.abc import Sequence

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.pit import PitCutoff


class MemoryFeatureRepository:
    def __init__(
        self,
        rows: Sequence[FeatureValue],
        *,
        contract: VisibilityContract,
    ) -> None:
        self._rows = tuple(rows)
        self._contract = contract

    def scan_window(
        self,
        *,
        as_of: date,
        feature_id: str,
        definition_version: str,
        param_hash: str,
        start: date,
        end: date,
    ) -> tuple[FeatureValue, ...]:
        if not feature_id.strip() or not definition_version.strip() or not param_hash.strip():
            raise FeatureLookupError("feature_id / definition_version / param_hash 为空")
        if start > end:
            raise FeatureLookupError("start 晚于 end")
        cutoff = pit_cutoff(self._contract, as_of=as_of)
        matched = [
            row
            for row in self._rows
            if row.feature_id == feature_id
            and row.definition_version == definition_version
            and row.param_hash == param_hash
            and start <= row.event_dt <= end
            and is_cutoff_visible(value=_cutoff_value(row, cutoff), cutoff=cutoff)
        ]
        if not matched:
            raise EmptyDomainError(
                f"因子窗口为空: feature_id={feature_id} start={start.isoformat()} "
                f"end={end.isoformat()} as_of={as_of.isoformat()}"
            )
        return tuple(sorted(matched, key=lambda row: (row.asset_id, row.event_dt)))

    def scan_cross_section(
        self,
        *,
        as_of: date,
        event_dt: date,
    ) -> tuple[FeatureValue, ...]:
        cutoff = pit_cutoff(self._contract, as_of=as_of)
        matched = [
            row
            for row in self._rows
            if row.event_dt == event_dt
            and is_cutoff_visible(value=_cutoff_value(row, cutoff), cutoff=cutoff)
        ]
        if not matched:
            raise EmptyDomainError(
                f"因子截面为空: event_dt={event_dt.isoformat()} as_of={as_of.isoformat()}"
            )
        return tuple(
            sorted(
                matched,
                key=lambda row: (
                    row.asset_id,
                    row.feature_id,
                    row.definition_version,
                    row.param_hash,
                ),
            )
        )

    def build_training_matrix(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        feature_ids: Sequence[str],
        asset_ids: Sequence[str],
    ) -> tuple[FeatureMatrixRow, ...]:
        if start > end:
            raise FeatureLookupError("start 晚于 end")
        features = list(feature_ids)
        assets = list(asset_ids)
        if not features:
            raise EmptyDomainError("feature_ids 为空，拒绝查询")
        if not assets:
            raise EmptyDomainError("asset_ids 为空，拒绝查询")
        cutoff = pit_cutoff(self._contract, as_of=as_of)
        feature_set = set(features)
        asset_set = set(assets)
        grouped: dict[tuple[str, date], dict[str, float]] = {}
        for row in self._rows:
            if row.asset_id not in asset_set or row.feature_id not in feature_set:
                continue
            if not start <= row.event_dt <= end:
                continue
            if not is_cutoff_visible(value=_cutoff_value(row, cutoff), cutoff=cutoff):
                continue
            key = (row.asset_id, row.event_dt)
            bucket = grouped.setdefault(key, {})
            # 与 DuckDB first(value) 对齐：按输入行顺序取首次出现的值。
            if row.feature_id not in bucket:
                bucket[row.feature_id] = row.value
        if not grouped:
            raise EmptyDomainError("训练矩阵源行为空，拒绝 pivot")
        return tuple(
            FeatureMatrixRow(
                asset_id=asset_id,
                event_dt=event_dt,
                values={fid: grouped[(asset_id, event_dt)].get(fid) for fid in features},
            )
            for asset_id, event_dt in sorted(grouped)
        )


def _cutoff_value(row: FeatureValue, cutoff: PitCutoff) -> date:
    try:
        raw = getattr(row, cutoff.column)
    except AttributeError as exc:
        raise FeatureLookupError(f"行缺少可见性列 {cutoff.column}") from exc
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    raise FeatureLookupError(f"{cutoff.column} 无法转为 date: {raw!r}")
