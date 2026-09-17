"""派生数据集契约：五张表成对、evaluation_only 不能进特征、样本能过 pandera。"""

from __future__ import annotations

import pandas as pd
import pytest
from pandera.errors import SchemaError

from quantagent.contracts.check import run_check
from quantagent.contracts.loader import load_bundle
from quantagent.contracts.pandera_schema import to_pandera
from quantagent.contracts.spec import LONG_SHORT_GROUP_NO, NO_BENCHMARK_ID
from quantagent.platform.storage import detect_repo_root

_DATASETS = (
    "mart.universe_member",
    "mart.forward_return",
    "feature.value",
    "feature.metric",
    "signal.group_nav",
)


@pytest.mark.contracts
def test_derived_datasets_are_paired() -> None:
    bundle = load_bundle()
    for dataset in _DATASETS:
        assert dataset in bundle.schemas, dataset
        assert dataset in bundle.visibilities, dataset
    report = run_check(bundle=bundle, repo_root=detect_repo_root())
    assert report.ok, [issue.render() for issue in report.issues]


@pytest.mark.contracts
def test_forward_return_is_evaluation_only() -> None:
    bundle = load_bundle()
    assert bundle.schemas["mart.forward_return"].usage == "evaluation_only"
    assert "mart.forward_return" not in bundle.schemas["feature.value"].reads
    assert "mart.forward_return" in bundle.schemas["feature.metric"].reads
    vis = bundle.visibilities["mart.forward_return"]
    assert vis.visibility.rule == "source_field"
    assert vis.visibility.field == "knowledge_dt"


@pytest.mark.contracts
def test_universe_member_is_interval() -> None:
    schema = load_bundle().schemas["mart.universe_member"]
    assert schema.temporal_kind == "interval"
    assert schema.columns["valid_to"].nullable is True
    assert schema.keys == ["universe_id", "asset_id", "valid_from"]


@pytest.mark.contracts
def test_group_nav_long_short_sentinel_and_run_key() -> None:
    schema = load_bundle().schemas["signal.group_nav"]
    assert "group_no" in schema.columns
    assert "run_id" in schema.keys
    assert "knowledge_dt" in schema.columns


@pytest.mark.contracts
def test_universe_member_pandera_sample() -> None:
    spec = load_bundle().schemas["mart.universe_member"]
    frame = pd.DataFrame(
        {
            "universe_id": ["u1"],
            "asset_id": ["000001.SZ"],
            "valid_from": ["2024-01-02"],
            "valid_to": [None],
            "member_weight": [None],
            "knowledge_dt": ["2023-12-15"],
            "pit_grade": ["B"],
        }
    )
    to_pandera(spec).validate(frame)


@pytest.mark.contracts
def test_forward_return_pandera_rejects_null_value() -> None:
    spec = load_bundle().schemas["mart.forward_return"]
    frame = pd.DataFrame(
        {
            "asset_id": ["000001.SZ"],
            "event_dt": ["2024-01-02"],
            "horizon": ["20d"],
            "return_kind": ["total"],
            "benchmark_id": [NO_BENCHMARK_ID],
            "value": [None],
            "end_dt": ["2024-01-30"],
            "knowledge_dt": ["2024-01-30"],
            "pit_grade": ["A"],
        }
    )
    with pytest.raises(SchemaError):
        to_pandera(spec).validate(frame)


@pytest.mark.contracts
def test_feature_value_pandera_sample() -> None:
    spec = load_bundle().schemas["feature.value"]
    frame = pd.DataFrame(
        {
            "event_dt": ["2024-01-02"],
            "asset_id": ["000001.SZ"],
            "asset_class": ["stock"],
            "feature_id": ["mom_20d"],
            "definition_version": ["v1"],
            "param_hash": ["abc"],
            "value": [0.12],
            "knowledge_dt": ["2024-01-02"],
            "pit_grade": ["B"],
            "computed_at": ["2024-01-02T16:00:00"],
            "run_id": ["run1"],
        }
    )
    to_pandera(spec).validate(frame)


@pytest.mark.contracts
def test_feature_metric_daily_ic_is_a_row() -> None:
    spec = load_bundle().schemas["feature.metric"]
    frame = pd.DataFrame(
        {
            "event_dt": ["2024-01-02"],
            "feature_id": ["mom_20d"],
            "definition_version": ["v1"],
            "param_hash": ["abc"],
            "universe_id": ["u1"],
            "horizon": ["20d"],
            "metric_id": ["rank_ic"],
            "window": ["1d"],
            "benchmark_id": [NO_BENCHMARK_ID],
            "value": [0.05],
            "knowledge_dt": ["2024-01-30"],
            "pit_grade": ["B"],
            "computed_at": ["2024-02-01T10:00:00"],
            "run_id": ["run1"],
        }
    )
    to_pandera(spec).validate(frame)


@pytest.mark.contracts
def test_group_nav_pandera_sample() -> None:
    spec = load_bundle().schemas["signal.group_nav"]
    frame = pd.DataFrame(
        {
            "event_dt": ["2024-01-02"],
            "feature_id": ["mom_20d"],
            "definition_version": ["v1"],
            "param_hash": ["abc"],
            "universe_id": ["u1"],
            "horizon": ["20d"],
            "group_no": [LONG_SHORT_GROUP_NO],
            "group_return": [0.01],
            "group_nav": [1.01],
            "knowledge_dt": ["2024-01-30"],
            "pit_grade": ["B"],
            "pit_report": ["{}"],
            "run_id": ["run1"],
            "code_version": ["abc123"],
            "config_digest": ["def456"],
        }
    )
    to_pandera(spec).validate(frame)
