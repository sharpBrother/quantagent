"""quantagent/adapters/lake

Parquet + DuckDB 读取适配。会话由 ``platform.duck`` 创建，本层只翻译
领域读取请求（含强制 ``as_of``）为 SQL。
"""

from quantagent.adapters.lake.errors import EmptyDomainError, LakeAdapterError
from quantagent.adapters.lake.feature_metric import LakeFeatureMetricRepository
from quantagent.adapters.lake.feature_value import (
    FEATURE_VALUE_VIEW,
    LakeFeatureRepository,
    build_training_matrix,
    scan_feature_cross_section,
    scan_feature_window,
)
from quantagent.adapters.lake.forward_return import LakeForwardReturnRepository
from quantagent.adapters.lake.group_nav import LakeGroupNavRepository
from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.lake.universe_member import LakeUniverseRepository

__all__ = [
    "FEATURE_VALUE_VIEW",
    "EmptyDomainError",
    "LakeAdapterError",
    "LakeCalendarRepository",
    "LakeFeatureMetricRepository",
    "LakeFeatureRepository",
    "LakeForwardReturnRepository",
    "LakeGroupNavRepository",
    "LakeUniverseRepository",
    "build_training_matrix",
    "scan_feature_cross_section",
    "scan_feature_window",
]
