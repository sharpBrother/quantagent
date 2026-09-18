"""派生湖表研究读取：memory 与 lake 对同一组合成行、同一个 as_of 行为一致。"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from quantagent.adapters.lake.feature_metric import LakeFeatureMetricRepository
from quantagent.adapters.lake.forward_return import LakeForwardReturnRepository
from quantagent.adapters.lake.group_nav import LakeGroupNavRepository
from quantagent.adapters.memory.feature_metric import MemoryFeatureMetricRepository
from quantagent.adapters.memory.forward_return import MemoryForwardReturnRepository
from quantagent.adapters.memory.group_nav import MemoryGroupNavRepository
from quantagent.contracts.spec import LONG_SHORT_GROUP_NO, NO_BENCHMARK_ID, VisibilityContract
from quantagent.domain.errors import EmptyDomainError, InvalidQueryError
from quantagent.domain.feature_metric import FeatureMetric
from quantagent.domain.forward_return import ForwardReturn
from quantagent.domain.group_nav import GroupNav

if TYPE_CHECKING:
    from pathlib import Path

    from quantagent.domain.ports.feature_metric import FeatureMetricRepository
    from quantagent.domain.ports.forward_return import ForwardReturnRepository
    from quantagent.domain.ports.group_nav import GroupNavRepository

_COMPUTED = datetime(2024, 2, 1, 10, 0, 0)


def _source_field(*, dataset: str, doc_ref: str, grade: str) -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": dataset,
            "doc_ref": doc_ref,
            "temporal_kind": "point_event",
            "event_field": "event_dt",
            "visibility": {
                "rule": "source_field",
                "field": "knowledge_dt",
                "grade": grade,
                "rationale": "契约测试用的可见性规则说明必须足够长",
            },
            "pit_recoverable": True,
        }
    )


_FR_ROWS = (
    ForwardReturn(
        asset_id="A0000",
        event_dt=date(2024, 1, 2),
        horizon="20d",
        return_kind="total",
        benchmark_id=NO_BENCHMARK_ID,
        value=0.01,
        end_dt=date(2024, 1, 30),
        knowledge_dt=date(2024, 1, 30),
        pit_grade="A",
    ),
    ForwardReturn(
        asset_id="A0000",
        event_dt=date(2024, 1, 3),
        horizon="20d",
        return_kind="total",
        benchmark_id=NO_BENCHMARK_ID,
        value=0.02,
        end_dt=date(2024, 1, 31),
        knowledge_dt=date(2024, 1, 31),
        pit_grade="A",
    ),
    ForwardReturn(
        asset_id="A0001",
        event_dt=date(2024, 1, 2),
        horizon="5d",
        return_kind="total",
        benchmark_id=NO_BENCHMARK_ID,
        value=0.03,
        end_dt=date(2024, 1, 9),
        knowledge_dt=date(2024, 1, 9),
        pit_grade="A",
    ),
)

_METRIC_ROWS = (
    FeatureMetric(
        event_dt=date(2024, 1, 2),
        feature_id="mom_20d",
        definition_version="v1",
        param_hash="p0",
        universe_id="u1",
        horizon="20d",
        metric_id="rank_ic",
        window="1d",
        benchmark_id=NO_BENCHMARK_ID,
        value=0.05,
        knowledge_dt=date(2024, 1, 30),
        pit_grade="B",
        computed_at=_COMPUTED,
        run_id="t",
    ),
    FeatureMetric(
        event_dt=date(2024, 1, 3),
        feature_id="mom_20d",
        definition_version="v1",
        param_hash="p0",
        universe_id="u1",
        horizon="20d",
        metric_id="rank_ic",
        window="1d",
        benchmark_id=NO_BENCHMARK_ID,
        value=0.06,
        knowledge_dt=date(2024, 1, 31),
        pit_grade="B",
        computed_at=_COMPUTED,
        run_id="t",
    ),
)

_NAV_ROWS = (
    GroupNav(
        event_dt=date(2024, 1, 2),
        feature_id="mom_20d",
        definition_version="v1",
        param_hash="p0",
        universe_id="u1",
        horizon="20d",
        group_no=LONG_SHORT_GROUP_NO,
        group_return=0.01,
        group_nav=1.01,
        knowledge_dt=date(2024, 1, 30),
        pit_grade="B",
        pit_report="{}",
        run_id="t",
        code_version="abc",
        config_digest="def",
    ),
    GroupNav(
        event_dt=date(2024, 1, 2),
        feature_id="mom_20d",
        definition_version="v1",
        param_hash="p0",
        universe_id="u1",
        horizon="20d",
        group_no=1,
        group_return=0.02,
        group_nav=1.02,
        knowledge_dt=date(2024, 1, 30),
        pit_grade="B",
        pit_report="{}",
        run_id="t",
        code_version="abc",
        config_digest="def",
    ),
    GroupNav(
        event_dt=date(2024, 1, 3),
        feature_id="mom_20d",
        definition_version="v1",
        param_hash="p0",
        universe_id="u1",
        horizon="20d",
        group_no=LONG_SHORT_GROUP_NO,
        group_return=0.03,
        group_nav=1.04,
        knowledge_dt=date(2024, 1, 31),
        pit_grade="B",
        pit_report="{}",
        run_id="t",
        code_version="abc",
        config_digest="def",
    ),
)


def _write_forward_return(path: Path) -> Path:
    table = pa.table(
        {
            "asset_id": [row.asset_id for row in _FR_ROWS],
            "event_dt": pa.array([row.event_dt for row in _FR_ROWS], type=pa.date32()),
            "horizon": [row.horizon for row in _FR_ROWS],
            "return_kind": [row.return_kind for row in _FR_ROWS],
            "benchmark_id": [row.benchmark_id for row in _FR_ROWS],
            "value": pa.array([row.value for row in _FR_ROWS], type=pa.float64()),
            "end_dt": pa.array([row.end_dt for row in _FR_ROWS], type=pa.date32()),
            "knowledge_dt": pa.array([row.knowledge_dt for row in _FR_ROWS], type=pa.date32()),
            "pit_grade": [row.pit_grade for row in _FR_ROWS],
        }
    )
    dest = path / "part-00000.parquet"
    pq.write_table(table, dest)
    return path


def _write_metric(path: Path) -> Path:
    table = pa.table(
        {
            "event_dt": pa.array([row.event_dt for row in _METRIC_ROWS], type=pa.date32()),
            "feature_id": [row.feature_id for row in _METRIC_ROWS],
            "definition_version": [row.definition_version for row in _METRIC_ROWS],
            "param_hash": [row.param_hash for row in _METRIC_ROWS],
            "universe_id": [row.universe_id for row in _METRIC_ROWS],
            "horizon": [row.horizon for row in _METRIC_ROWS],
            "metric_id": [row.metric_id for row in _METRIC_ROWS],
            "window": [row.window for row in _METRIC_ROWS],
            "benchmark_id": [row.benchmark_id for row in _METRIC_ROWS],
            "value": pa.array([row.value for row in _METRIC_ROWS], type=pa.float64()),
            "knowledge_dt": pa.array([row.knowledge_dt for row in _METRIC_ROWS], type=pa.date32()),
            "pit_grade": [row.pit_grade for row in _METRIC_ROWS],
            "computed_at": pa.array(
                [row.computed_at for row in _METRIC_ROWS], type=pa.timestamp("us")
            ),
            "run_id": [row.run_id for row in _METRIC_ROWS],
        }
    )
    dest = path / "part-00000.parquet"
    pq.write_table(table, dest)
    return path


def _write_group_nav(path: Path) -> Path:
    table = pa.table(
        {
            "event_dt": pa.array([row.event_dt for row in _NAV_ROWS], type=pa.date32()),
            "feature_id": [row.feature_id for row in _NAV_ROWS],
            "definition_version": [row.definition_version for row in _NAV_ROWS],
            "param_hash": [row.param_hash for row in _NAV_ROWS],
            "universe_id": [row.universe_id for row in _NAV_ROWS],
            "horizon": [row.horizon for row in _NAV_ROWS],
            "group_no": pa.array([row.group_no for row in _NAV_ROWS], type=pa.int64()),
            "group_return": pa.array([row.group_return for row in _NAV_ROWS], type=pa.float64()),
            "group_nav": pa.array([row.group_nav for row in _NAV_ROWS], type=pa.float64()),
            "knowledge_dt": pa.array([row.knowledge_dt for row in _NAV_ROWS], type=pa.date32()),
            "pit_grade": [row.pit_grade for row in _NAV_ROWS],
            "pit_report": [row.pit_report for row in _NAV_ROWS],
            "run_id": [row.run_id for row in _NAV_ROWS],
            "code_version": [row.code_version for row in _NAV_ROWS],
            "config_digest": [row.config_digest for row in _NAV_ROWS],
        }
    )
    dest = path / "part-00000.parquet"
    pq.write_table(table, dest)
    return path


def _scan_fr(repo: ForwardReturnRepository, *, as_of: date) -> tuple[ForwardReturn, ...]:
    return repo.scan_window(
        as_of=as_of,
        horizon="20d",
        return_kind="total",
        benchmark_id=NO_BENCHMARK_ID,
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
    )


def _scan_metric(repo: FeatureMetricRepository, *, as_of: date) -> tuple[FeatureMetric, ...]:
    return repo.scan_window(
        as_of=as_of,
        feature_id="mom_20d",
        definition_version="v1",
        param_hash="p0",
        universe_id="u1",
        horizon="20d",
        metric_id="rank_ic",
        window="1d",
        benchmark_id=NO_BENCHMARK_ID,
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
    )


def _scan_nav(repo: GroupNavRepository, *, as_of: date) -> tuple[GroupNav, ...]:
    return repo.scan_window(
        as_of=as_of,
        feature_id="mom_20d",
        definition_version="v1",
        param_hash="p0",
        universe_id="u1",
        horizon="20d",
        run_id="t",
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
    )


@pytest.mark.contracts
def test_forward_return_memory_and_lake_match(tmp_path: Path) -> None:
    contract = _source_field(
        dataset="mart.forward_return",
        doc_ref="docs/architecture/derived-datasets.md",
        grade="A",
    )
    memory = MemoryForwardReturnRepository(_FR_ROWS, contract=contract)
    lake = LakeForwardReturnRepository(_write_forward_return(tmp_path), contract=contract)
    as_of = date(2024, 1, 30)
    visible = _scan_fr(memory, as_of=as_of)
    assert [row.event_dt for row in visible] == [date(2024, 1, 2)]
    assert all(row.knowledge_dt <= as_of for row in visible)
    with pytest.raises(EmptyDomainError):
        _scan_fr(memory, as_of=date(2024, 1, 29))
    with pytest.raises(InvalidQueryError):
        memory.scan_window(
            as_of=as_of,
            horizon="20d",
            return_kind="total",
            benchmark_id=NO_BENCHMARK_ID,
            start=date(2024, 2, 1),
            end=date(2024, 1, 1),
        )
    assert _scan_fr(lake, as_of=as_of) == visible


@pytest.mark.contracts
def test_feature_metric_does_not_use_event_dt_as_visible(tmp_path: Path) -> None:
    contract = _source_field(
        dataset="feature.metric",
        doc_ref="docs/architecture/derived-datasets.md",
        grade="B",
    )
    memory = MemoryFeatureMetricRepository(_METRIC_ROWS, contract=contract)
    lake = LakeFeatureMetricRepository(_write_metric(tmp_path), contract=contract)
    as_of = date(2024, 1, 30)
    visible = _scan_metric(memory, as_of=as_of)
    assert [row.event_dt for row in visible] == [date(2024, 1, 2)]
    with pytest.raises(EmptyDomainError):
        _scan_metric(memory, as_of=date(2024, 1, 3))
    assert _scan_metric(lake, as_of=as_of) == visible


@pytest.mark.contracts
def test_group_nav_keeps_long_short_and_drops_unrealized(tmp_path: Path) -> None:
    contract = _source_field(
        dataset="signal.group_nav",
        doc_ref="docs/architecture/derived-datasets.md",
        grade="B",
    )
    memory = MemoryGroupNavRepository(_NAV_ROWS, contract=contract)
    lake = LakeGroupNavRepository(_write_group_nav(tmp_path), contract=contract)
    as_of = date(2024, 1, 30)
    visible = _scan_nav(memory, as_of=as_of)
    assert [(row.event_dt, row.group_no) for row in visible] == [
        (date(2024, 1, 2), LONG_SHORT_GROUP_NO),
        (date(2024, 1, 2), 1),
    ]
    with pytest.raises(EmptyDomainError):
        _scan_nav(memory, as_of=date(2024, 1, 3))
    assert _scan_nav(lake, as_of=as_of) == visible
