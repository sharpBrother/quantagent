"""quantagent/adapters/lake

Parquet + DuckDB 读取适配。会话由 ``platform.duck`` 创建，本层只翻译
领域读取请求（含强制 ``as_of``）为 SQL。
"""

from quantagent.adapters.lake.errors import EmptyDomainError, LakeAdapterError
from quantagent.adapters.lake.feature_value import (
    FEATURE_VALUE_VIEW,
    build_training_matrix,
    scan_feature_cross_section,
    scan_feature_window,
)

__all__ = [
    "FEATURE_VALUE_VIEW",
    "EmptyDomainError",
    "LakeAdapterError",
    "build_training_matrix",
    "scan_feature_cross_section",
    "scan_feature_window",
]
