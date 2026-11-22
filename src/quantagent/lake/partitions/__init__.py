"""quantagent/lake/partitions
因子长表等数据集的分区键、排序键、压缩与写入。
物理参数以 ``docs/adr/2026-09-17-feature-value-parquet-layout.md`` 为准。
``mart.forward_return`` 有独立布局，不复用 ``FeatureValueLayout``。
"""

from quantagent.lake.partitions.forward_return import (
    FROZEN_FORWARD_RETURN_LAYOUT,
    ForwardReturnLayout,
    write_forward_return_parquet,
)
from quantagent.lake.partitions.layout import (
    FROZEN_FEATURE_VALUE_LAYOUT,
    FeatureValueLayout,
    LakeLayoutError,
)
from quantagent.lake.partitions.write import write_feature_value_parquet

__all__ = [
    "FROZEN_FEATURE_VALUE_LAYOUT",
    "FROZEN_FORWARD_RETURN_LAYOUT",
    "FeatureValueLayout",
    "ForwardReturnLayout",
    "LakeLayoutError",
    "write_feature_value_parquet",
    "write_forward_return_parquet",
]
