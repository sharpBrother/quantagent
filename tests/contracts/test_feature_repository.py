"""FeatureRepository：memory 与 lake 对同一组行、同一个 as_of 行为一致。"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from quantagent.adapters.lake.feature_value import LakeFeatureRepository
from quantagent.adapters.memory.feature_value import MemoryFeatureRepository
from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.errors import EmptyDomainError, FeatureLookupError
from quantagent.domain.feature_value import FeatureMatrixRow, FeatureValue

if TYPE_CHECKING:
    from pathlib import Path

    from quantagent.domain.ports.feature import FeatureRepository

_COMPUTED = datetime(2024, 6, 1)
_ROWS = (
    FeatureValue(
        event_dt=date(2024, 1, 2),
        asset_id="A0000",
        asset_class="stock",
        feature_id="mom_20d",
        definition_version="v1",
        param_hash="p0",
        value=1.0,
        knowledge_dt=date(2024, 1, 3),
        pit_grade="A",
        computed_at=_COMPUTED,
        run_id="t",
    ),
    FeatureValue(
        event_dt=date(2024, 1, 3),
        asset_id="A0000",
        asset_class="stock",
        feature_id="mom_20d",
        definition_version="v1",
        param_hash="p0",
        value=2.0,
        knowledge_dt=date(2024, 1, 4),
        pit_grade="A",
        computed_at=_COMPUTED,
        run_id="t",
    ),
    FeatureValue(
        event_dt=date(2024, 1, 3),
        asset_id="A0001",
        asset_class="stock",
        feature_id="mom_20d",
        definition_version="v1",
        param_hash="p0",
        value=3.0,
        knowledge_dt=date(2024, 1, 20),
        pit_grade="A",
        computed_at=_COMPUTED,
        run_id="t",
    ),
    FeatureValue(
        event_dt=date(2024, 1, 3),
        asset_id="A0000",
        asset_class="stock",
        feature_id="turn_20d",
        definition_version="v1",
        param_hash="p0",
        value=4.0,
        knowledge_dt=date(2024, 1, 4),
        pit_grade="A",
        computed_at=_COMPUTED,
        run_id="t",
    ),
    FeatureValue(
        event_dt=date(2024, 1, 3),
        asset_id="A0001",
        asset_class="stock",
        feature_id="turn_20d",
        definition_version="v1",
        param_hash="p0",
        value=5.0,
        knowledge_dt=date(2024, 1, 4),
        pit_grade="A",
        computed_at=_COMPUTED,
        run_id="t",
    ),
)


def _contract() -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": "feature.value",
            "doc_ref": "docs/architecture/feature-storage.md",
            "temporal_kind": "point_event",
            "event_field": "event_dt",
            "visibility": {
                "rule": "source_field",
                "field": "knowledge_dt",
                "grade": "B",
                "rationale": "契约测试用的因子可见性规则说明足够长",
            },
            "pit_recoverable": True,
        }
    )


def _write_parquet(path: Path) -> Path:
    table = pa.table(
        {
            "event_dt": pa.array([row.event_dt for row in _ROWS], type=pa.date32()),
            "asset_id": [row.asset_id for row in _ROWS],
            "asset_class": [row.asset_class for row in _ROWS],
            "feature_id": [row.feature_id for row in _ROWS],
            "definition_version": [row.definition_version for row in _ROWS],
            "param_hash": [row.param_hash for row in _ROWS],
            "value": pa.array([row.value for row in _ROWS], type=pa.float64()),
            "knowledge_dt": pa.array([row.knowledge_dt for row in _ROWS], type=pa.date32()),
            "pit_grade": [row.pit_grade for row in _ROWS],
            "computed_at": pa.array([row.computed_at for row in _ROWS], type=pa.timestamp("us")),
            "run_id": [row.run_id for row in _ROWS],
        }
    )
    dest = path / "part-00000.parquet"
    pq.write_table(table, dest)
    return path


def _scan_window(repo: FeatureRepository, *, as_of: date) -> tuple[FeatureValue, ...]:
    return repo.scan_window(
        as_of=as_of,
        feature_id="mom_20d",
        definition_version="v1",
        param_hash="p0",
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
    )


def _scan_matrix(repo: FeatureRepository, *, as_of: date) -> tuple[FeatureMatrixRow, ...]:
    return repo.build_training_matrix(
        as_of=as_of,
        start=date(2024, 1, 3),
        end=date(2024, 1, 3),
        feature_ids=["mom_20d", "turn_20d"],
        asset_ids=["A0000", "A0001"],
    )


def _assert_repo(repo: FeatureRepository) -> None:
    as_of = date(2024, 1, 10)
    window = _scan_window(repo, as_of=as_of)
    assert [(row.asset_id, row.event_dt) for row in window] == [
        ("A0000", date(2024, 1, 2)),
        ("A0000", date(2024, 1, 3)),
    ]
    assert all(row.knowledge_dt <= as_of for row in window)

    with pytest.raises(EmptyDomainError):
        _scan_window(repo, as_of=date(2024, 1, 2))

    cross = repo.scan_cross_section(as_of=as_of, event_dt=date(2024, 1, 3))
    keys = {(row.asset_id, row.feature_id) for row in cross}
    assert ("A0001", "mom_20d") not in keys
    assert ("A0000", "mom_20d") in keys
    assert len(cross) == 3

    matrix = _scan_matrix(repo, as_of=as_of)
    by_asset = {row.asset_id: row for row in matrix}
    assert by_asset["A0000"].values["mom_20d"] == 2.0
    assert by_asset["A0000"].values["turn_20d"] == 4.0
    assert "A0001" in by_asset
    assert by_asset["A0001"].values["mom_20d"] is None
    assert by_asset["A0001"].values["turn_20d"] == 5.0

    with pytest.raises(EmptyDomainError, match="asset_ids"):
        repo.build_training_matrix(
            as_of=as_of,
            start=date(2024, 1, 1),
            end=date(2024, 1, 31),
            feature_ids=["mom_20d"],
            asset_ids=[],
        )
    with pytest.raises(FeatureLookupError):
        repo.scan_window(
            as_of=as_of,
            feature_id="mom_20d",
            definition_version="v1",
            param_hash="p0",
            start=date(2024, 2, 1),
            end=date(2024, 1, 1),
        )


@pytest.mark.contracts
def test_memory_feature_applies_source_field() -> None:
    _assert_repo(MemoryFeatureRepository(_ROWS, contract=_contract()))


@pytest.mark.contracts
def test_lake_feature_matches_memory(tmp_path: Path) -> None:
    source = _write_parquet(tmp_path)
    lake = LakeFeatureRepository(source, contract=_contract())
    memory = MemoryFeatureRepository(_ROWS, contract=_contract())
    _assert_repo(lake)
    as_of = date(2024, 1, 10)
    assert _scan_window(lake, as_of=as_of) == _scan_window(memory, as_of=as_of)
    assert lake.scan_cross_section(
        as_of=as_of, event_dt=date(2024, 1, 3)
    ) == memory.scan_cross_section(as_of=as_of, event_dt=date(2024, 1, 3))
    assert _scan_matrix(lake, as_of=as_of) == _scan_matrix(memory, as_of=as_of)
