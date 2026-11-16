"""把因子长表行写成冻结布局的 Parquet。默认不覆盖既有分区。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import pyarrow as pa

from quantagent.contracts.loader import load_bundle
from quantagent.contracts.pandera_schema import to_pandera
from quantagent.lake.partitions import FROZEN_FEATURE_VALUE_LAYOUT, write_feature_value_parquet
from quantagent.lake.partitions.layout import LakeLayoutError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from quantagent.domain.feature_value import FeatureValue

DATASET = "feature.value"


def write_feature_values(rows: Sequence[FeatureValue], dest: Path) -> dict[str, int]:
    if not rows:
        raise LakeLayoutError("没有可写入的因子行")
    frame = pd.DataFrame(
        {
            "event_dt": [row.event_dt for row in rows],
            "asset_id": [row.asset_id for row in rows],
            "asset_class": [row.asset_class for row in rows],
            "feature_id": [row.feature_id for row in rows],
            "definition_version": [row.definition_version for row in rows],
            "param_hash": [row.param_hash for row in rows],
            "value": [row.value for row in rows],
            "knowledge_dt": [row.knowledge_dt for row in rows],
            "pit_grade": [row.pit_grade for row in rows],
            "computed_at": [row.computed_at for row in rows],
            "run_id": [row.run_id for row in rows],
        }
    )
    to_pandera(load_bundle().schemas[DATASET]).validate(frame)
    table = pa.Table.from_pandas(frame, preserve_index=False)
    return write_feature_value_parquet(table, dest, FROZEN_FEATURE_VALUE_LAYOUT)
