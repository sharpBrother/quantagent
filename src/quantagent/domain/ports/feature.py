"""因子长表仓储。只取回 as_of 可见的行；不计算、不写入。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from quantagent.domain.feature_value import FeatureMatrixRow, FeatureValue


class FeatureRepository(Protocol):
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
        """``[start, end]`` 内、``as_of`` 可见的单因子长表行。

        无行则 ``EmptyDomainError``。不提供省略 ``as_of`` 的重载。
        """
        ...

    def scan_cross_section(
        self,
        *,
        as_of: date,
        event_dt: date,
    ) -> tuple[FeatureValue, ...]:
        """某一 ``event_dt`` 上、``as_of`` 可见的全因子截面。无行则空域。"""
        ...

    def build_training_matrix(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        feature_ids: Sequence[str],
        asset_ids: Sequence[str],
    ) -> tuple[FeatureMatrixRow, ...]:
        """指定股票池与因子集合上的训练宽表。空域与空 id 列表 fail-closed。"""
        ...
