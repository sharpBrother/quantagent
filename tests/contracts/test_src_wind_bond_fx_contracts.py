"""债券曲线、债券回购与外汇的 Wind 源镜像契约：schema 列与写入规格一致，visibility 规则与口径一致。

口径见 docs/migration/wind-pipeline-handoff.md。这里只校验 YAML 与写入白名单的 native_columns，
不重新裁定规则。
"""

from __future__ import annotations

import pytest

from quantagent.contracts.check import run_check
from quantagent.contracts.loader import load_bundle
from quantagent.ingest.writers.tables import ALLOWED_SRC_WRITE_TARGETS
from quantagent.platform.storage import detect_repo_root

_DATASETS = (
    "src.wind.cbondcurvecnbd",
    "src.wind.cbondcurvecsi",
    "src.wind.cbondrepoandibleodprices",
    "src.wind.cbondpricesrepo",
    "src.wind.cbondrepo",
    "src.wind.fxeodprices",
)


@pytest.mark.contracts
@pytest.mark.parametrize("dataset", _DATASETS)
def test_schema_columns_follow_native_columns(dataset: str) -> None:
    bundle = load_bundle()
    schema = bundle.schemas[dataset]
    spec = ALLOWED_SRC_WRITE_TARGETS[dataset]
    assert tuple(schema.columns) == spec.native_columns
    assert schema.keys == ["OBJECT_ID"]
    assert schema.layer == "pg"
    assert schema.reads == []
    assert schema.event_field == "TRADE_DT"


@pytest.mark.contracts
@pytest.mark.parametrize("dataset", _DATASETS)
def test_visibility_is_same_day_close_point_event(dataset: str) -> None:
    bundle = load_bundle()
    vis = bundle.visibilities[dataset]
    assert vis.temporal_kind == "point_event"
    assert vis.event_field == "TRADE_DT"
    assert vis.visibility.rule == "same_day_close"
    assert vis.visibility.grade == "A"
    assert vis.visibility.field is None
    assert vis.visibility.fallback is None
    assert vis.pit_recoverable is True
    assert vis.doc_ref == "docs/migration/wind-pipeline-handoff.md"


@pytest.mark.contracts
def test_bond_fx_passes_contract_check() -> None:
    report = run_check(bundle=load_bundle(), repo_root=detect_repo_root())
    issues = [issue.render() for issue in report.issues if issue.dataset in _DATASETS]
    assert issues == []
