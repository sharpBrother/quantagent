"""feature.value 三类查询：强制 PIT 截止列，空域 fail-closed。"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from quantagent.adapters.lake import (
    FEATURE_VALUE_VIEW,
    EmptyDomainError,
    build_training_matrix,
    scan_feature_cross_section,
    scan_feature_window,
)
from quantagent.domain.feature_value import FeatureKey
from quantagent.platform.duck import duck_session, register_parquet

if TYPE_CHECKING:
    from pathlib import Path


def _table() -> pa.Table:
    rows = [
        (date(2024, 1, 2), "A0000", "stock", "mom_20d", 1.0, date(2024, 1, 3)),
        (date(2024, 1, 3), "A0000", "stock", "mom_20d", 2.0, date(2024, 1, 4)),
        (date(2024, 1, 3), "A0001", "stock", "mom_20d", 3.0, date(2024, 1, 20)),
        (date(2024, 1, 3), "A0000", "stock", "turn_20d", 4.0, date(2024, 1, 4)),
        (date(2024, 1, 3), "A0001", "stock", "turn_20d", 5.0, date(2024, 1, 4)),
    ]
    n = len(rows)
    return pa.table(
        {
            "event_dt": pa.array([r[0] for r in rows], type=pa.date32()),
            "asset_id": [r[1] for r in rows],
            "asset_class": [r[2] for r in rows],
            "feature_id": [r[3] for r in rows],
            "definition_version": ["v1"] * n,
            "param_hash": ["p0"] * n,
            "value": pa.array([r[4] for r in rows], type=pa.float64()),
            "knowledge_dt": pa.array([r[5] for r in rows], type=pa.date32()),
            "pit_grade": ["A"] * n,
            "computed_at": pa.array([datetime(2024, 6, 1)] * n, type=pa.timestamp("us")),
            "run_id": ["t"] * n,
        }
    )


@pytest.fixture
def feature_dir(tmp_path: Path) -> Path:
    dest = tmp_path / "feature" / "value"
    dest.mkdir(parents=True)
    pq.write_table(_table(), dest / "part-00000.parquet")
    return dest


@pytest.mark.unit
def test_window_drops_rows_not_yet_visible(feature_dir: Path) -> None:
    with duck_session() as conn:
        register_parquet(conn, FEATURE_VALUE_VIEW, feature_dir)
        table = scan_feature_window(
            conn,
            visibility_column="knowledge_dt",
            visible_on_or_before=date(2024, 1, 10),
            feature_id="mom_20d",
            definition_version="v1",
            param_hash="p0",
            start=date(2024, 1, 1),
            end=date(2024, 1, 31),
        )
    assets = table.column("asset_id").to_pylist()
    events = table.column("event_dt").to_pylist()
    assert list(zip(assets, events, strict=True)) == [
        ("A0000", date(2024, 1, 2)),
        ("A0000", date(2024, 1, 3)),
    ]


@pytest.mark.unit
def test_cross_section_is_one_day_and_pit(feature_dir: Path) -> None:
    with duck_session() as conn:
        register_parquet(conn, FEATURE_VALUE_VIEW, feature_dir)
        table = scan_feature_cross_section(
            conn,
            visibility_column="knowledge_dt",
            visible_on_or_before=date(2024, 1, 10),
            event_dt=date(2024, 1, 3),
        )
    keys = list(
        zip(
            table.column("asset_id").to_pylist(),
            table.column("feature_id").to_pylist(),
            strict=True,
        )
    )
    assert ("A0001", "mom_20d") not in keys
    assert ("A0000", "mom_20d") in keys
    assert ("A0000", "turn_20d") in keys
    assert table.num_rows == 3


@pytest.mark.unit
def test_window_cutoff_column_is_honored(feature_dir: Path) -> None:
    """WHERE 必须用传入的截止列。若 SQL 仍写死 knowledge_dt，改用 event_dt 也滤不进 A0001。"""
    with duck_session() as conn:
        register_parquet(conn, FEATURE_VALUE_VIEW, feature_dir)
        table = scan_feature_window(
            conn,
            visibility_column="event_dt",
            visible_on_or_before=date(2024, 1, 10),
            feature_id="mom_20d",
            definition_version="v1",
            param_hash="p0",
            start=date(2024, 1, 1),
            end=date(2024, 1, 31),
        )
    assert "A0001" in table.column("asset_id").to_pylist()


@pytest.mark.unit
def test_training_matrix_pivots_visible_values(feature_dir: Path) -> None:
    with duck_session() as conn:
        register_parquet(conn, FEATURE_VALUE_VIEW, feature_dir)
        table = build_training_matrix(
            conn,
            visibility_column="knowledge_dt",
            visible_on_or_before=date(2024, 1, 10),
            start=date(2024, 1, 3),
            end=date(2024, 1, 3),
            feature_keys=[FeatureKey("mom_20d", "v1", "p0"), FeatureKey("turn_20d", "v1", "p0")],
            asset_ids=["A0000", "A0001"],
        )
    names = set(table.column_names)
    assert {"asset_id", "event_dt", "mom_20d", "turn_20d"} <= names
    by_asset = {row["asset_id"]: row for row in table.to_pylist()}
    assert by_asset["A0000"]["mom_20d"] == 2.0
    assert by_asset["A0000"]["turn_20d"] == 4.0
    assert "A0001" in by_asset
    assert by_asset["A0001"]["mom_20d"] is None
    assert by_asset["A0001"]["turn_20d"] == 5.0


@pytest.mark.unit
def test_training_matrix_empty_universe_fails_closed(feature_dir: Path) -> None:
    with (
        duck_session() as conn,
        pytest.raises(EmptyDomainError, match="asset_ids"),
    ):
        register_parquet(conn, FEATURE_VALUE_VIEW, feature_dir)
        build_training_matrix(
            conn,
            visibility_column="knowledge_dt",
            visible_on_or_before=date(2024, 1, 10),
            start=date(2024, 1, 1),
            end=date(2024, 1, 31),
            feature_keys=[FeatureKey("mom_20d", "v1", "p0")],
            asset_ids=[],
        )
