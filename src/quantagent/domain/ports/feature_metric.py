"""因子评价指标仓储。只取回 as_of 可见的行；不计算。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date

    from quantagent.domain.feature_metric import FeatureMetric


class FeatureMetricRepository(Protocol):
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
        """``[start, end]`` 内、``as_of`` 可见的指标行。窗口按 ``event_dt``。

        无行则 ``EmptyDomainError``。不提供省略 ``as_of`` 的重载。
        """
        ...
