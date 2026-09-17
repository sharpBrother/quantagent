"""因子长表布局：禁止 feature_id 分区，默认不覆盖。"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

import pyarrow as pa
import pytest

from quantagent.lake.layout_bench import CANDIDATE_LAYOUTS
from quantagent.lake.partitions import (
    FROZEN_FEATURE_VALUE_LAYOUT,
    FeatureValueLayout,
    LakeLayoutError,
    write_feature_value_parquet,
)

if TYPE_CHECKING:
    from pathlib import Path


def _one_row() -> pa.Table:
    return pa.table(
        {
            "event_dt": pa.array([date(2024, 1, 15)], type=pa.date32()),
            "asset_id": ["A0000"],
            "asset_class": ["stock"],
            "feature_id": ["f000"],
            "definition_version": ["v1"],
            "param_hash": ["p0"],
            "value": pa.array([1.0], type=pa.float64()),
            "knowledge_dt": pa.array([date(2024, 1, 16)], type=pa.date32()),
            "pit_grade": ["A"],
            "computed_at": pa.array([datetime(2024, 6, 1)], type=pa.timestamp("us")),
            "run_id": ["t"],
        }
    )


@pytest.mark.unit
def test_feature_id_partition_is_rejected() -> None:
    with pytest.raises(LakeLayoutError, match="feature_id"):
        FeatureValueLayout(
            name="bad",
            partition_keys=("feature_id",),
            sort_keys=("event_dt", "asset_id"),
            compression="zstd",
        ).validate()


@pytest.mark.unit
def test_frozen_layout_does_not_partition_by_feature() -> None:
    FROZEN_FEATURE_VALUE_LAYOUT.validate()
    assert "feature_id" not in FROZEN_FEATURE_VALUE_LAYOUT.partition_keys
    assert FROZEN_FEATURE_VALUE_LAYOUT.partition_keys == ("asset_class", "ym")
    assert FROZEN_FEATURE_VALUE_LAYOUT.compression == "zstd"
    assert any(item.name == FROZEN_FEATURE_VALUE_LAYOUT.name for item in CANDIDATE_LAYOUTS)


@pytest.mark.unit
def test_write_refuses_overwrite(tmp_path: Path) -> None:
    dest = tmp_path / "layout"
    layout = FeatureValueLayout(
        name="ym_event",
        partition_keys=("ym",),
        sort_keys=("event_dt", "asset_id", "feature_id"),
        compression="zstd",
    )
    write_feature_value_parquet(_one_row(), dest, layout)
    assert list(dest.rglob("*.parquet"))
    with pytest.raises(LakeLayoutError, match="拒绝覆盖"):
        write_feature_value_parquet(_one_row(), dest, layout)
