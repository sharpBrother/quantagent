"""Wind 第一批 10 张源镜像的契约：schema 列与写入规格一致，visibility 规则与口径一致。

口径由项目负责人裁定，见 docs/contracts/src-wind-first-batch.md。这里只校验
YAML 与裁定口径、与写入白名单的 native_columns 是否一致，不重新裁定规则。
"""

from __future__ import annotations

import pytest

from quantagent.contracts.check import run_check
from quantagent.contracts.loader import load_bundle
from quantagent.ingest.writers.tables import ALLOWED_SRC_WRITE_TARGETS
from quantagent.platform.storage import detect_repo_root

# (dataset, temporal_kind, visibility rule, visibility field, event_field, period_fields)
_CASES: list[tuple[str, str, str, str | None, str | None, tuple[str, ...] | None]] = [
    # A 组：交易所日频点事件，same_day_close。
    ("src.wind.asharemoneyflow", "point_event", "same_day_close", None, "TRADE_DT", None),
    (
        "src.wind.ashareeodderivativeindicator",
        "point_event",
        "same_day_close",
        None,
        "TRADE_DT",
        None,
    ),
    ("src.wind.aindexvaluation", "point_event", "same_day_close", None, "TRADE_DT", None),
    (
        "src.wind.aindexindustrieseodcitics",
        "point_event",
        "same_day_close",
        None,
        "TRADE_DT",
        None,
    ),
    ("src.wind.asharemargintradesum", "point_event", "same_day_close", None, "TRADE_DT", None),
    # B 组：财报与财务指标，source_field ANN_DT，不写 fallback。
    (
        "src.wind.ashareincome",
        "period_with_revision",
        "source_field",
        "ANN_DT",
        None,
        ("REPORT_PERIOD", "STATEMENT_TYPE"),
    ),
    (
        "src.wind.asharecashflow",
        "period_with_revision",
        "source_field",
        "ANN_DT",
        None,
        ("REPORT_PERIOD", "STATEMENT_TYPE"),
    ),
    (
        "src.wind.asharebalancesheet",
        "period_with_revision",
        "source_field",
        "ANN_DT",
        None,
        ("REPORT_PERIOD", "STATEMENT_TYPE"),
    ),
    (
        "src.wind.asharefinancialindicator",
        "period_with_revision",
        "source_field",
        "ANN_DT",
        None,
        ("REPORT_PERIOD", "STATEMENT_TYPE"),
    ),
    # C 组：业绩预告，source_field S_PROFITNOTICE_DATE。
    (
        "src.wind.ashareprofitnotice",
        "period_with_revision",
        "source_field",
        "S_PROFITNOTICE_DATE",
        None,
        ("S_PROFITNOTICE_PERIOD",),
    ),
]

_DATASETS = frozenset(case[0] for case in _CASES)


@pytest.mark.contracts
@pytest.mark.parametrize("dataset", [case[0] for case in _CASES])
def test_schema_columns_follow_native_columns(dataset: str) -> None:
    bundle = load_bundle()
    schema = bundle.schemas[dataset]
    spec = ALLOWED_SRC_WRITE_TARGETS[dataset]
    assert tuple(schema.columns) == spec.native_columns
    assert schema.keys == ["OBJECT_ID"]
    assert schema.layer == "pg"
    assert schema.reads == []


@pytest.mark.contracts
@pytest.mark.parametrize(("dataset", "kind", "rule", "field", "event", "period"), _CASES)
def test_visibility_matches_ruling(
    *,
    dataset: str,
    kind: str,
    rule: str,
    field: str | None,
    event: str | None,
    period: tuple[str, ...] | None,
) -> None:
    bundle = load_bundle()
    vis = bundle.visibilities[dataset]
    assert vis.temporal_kind == kind
    assert vis.visibility.rule == rule
    assert vis.visibility.grade == "A"
    assert vis.visibility.field == field
    assert vis.visibility.fallback is None
    assert vis.event_field == event
    assert (tuple(vis.period_fields) if vis.period_fields else None) == period
    assert vis.pit_recoverable is True


@pytest.mark.contracts
def test_first_batch_passes_contract_check() -> None:
    report = run_check(bundle=load_bundle(), repo_root=detect_repo_root())
    issues = [issue.render() for issue in report.issues if issue.dataset in _DATASETS]
    assert issues == []
