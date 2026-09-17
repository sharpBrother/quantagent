"""可见性规则模型：fallback 不得抬高等级，缺规则字段要失败。"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from quantagent.contracts.spec import DatasetSchemaSpec, VisibilityContract, VisibilitySpec


@pytest.mark.unit
def test_fallback_grade_cannot_be_better_than_primary() -> None:
    with pytest.raises(ValidationError, match="fallback"):
        VisibilitySpec(
            rule="source_field",
            field="ann_dt",
            grade="B",
            rationale="主规则用公告日，缺省时不得抬到 A",
            fallback=VisibilitySpec(
                rule="same_day_close",
                grade="A",
                rationale="这会把推断结果标得比原生字段更可信",
            ),
        )


@pytest.mark.unit
def test_same_grade_fallback_is_allowed() -> None:
    spec = VisibilitySpec(
        rule="source_field",
        field="ann_dt",
        grade="B",
        rationale="主规则与 fallback 同级是允许的",
        fallback=VisibilitySpec(
            rule="fixed_lag",
            grade="B",
            rationale="固定延迟与公告日同为制度性规则",
            lag_n=1,
            lag_unit="trading_day",
        ),
    )
    assert spec.fallback is not None
    assert spec.fallback.grade == "B"


@pytest.mark.unit
def test_source_field_requires_field() -> None:
    with pytest.raises(ValidationError, match="field"):
        VisibilitySpec(rule="source_field", grade="A", rationale="缺少 field 应失败")


@pytest.mark.unit
def test_unrecoverable_requires_pit_from() -> None:
    with pytest.raises(ValidationError, match="pit_from"):
        VisibilityContract(
            dataset="mart.legacy_x",
            doc_ref="docs/contracts/trade-calendar.md",
            temporal_kind="point_event",
            event_field="event_dt",
            visibility=VisibilitySpec(
                rule="ingest_time",
                grade="D",
                rationale="存量迁入不能没有起算日",
            ),
            pit_recoverable=False,
        )


@pytest.mark.unit
def test_unrecoverable_with_pit_from_ok() -> None:
    spec = VisibilityContract(
        dataset="mart.legacy_x",
        doc_ref="docs/contracts/trade-calendar.md",
        temporal_kind="point_event",
        event_field="event_dt",
        visibility=VisibilitySpec(
            rule="ingest_time",
            grade="D",
            rationale="存量迁入，历史修订不可恢复",
        ),
        pit_recoverable=False,
        pit_from=date(2026, 9, 16),
    )
    assert spec.pit_from == date(2026, 9, 16)


@pytest.mark.unit
def test_published_at_must_be_nullable() -> None:
    with pytest.raises(ValidationError, match="published_at"):
        DatasetSchemaSpec(
            dataset="mart.example",
            layer="lake",
            doc_ref="docs/contracts/trade-calendar.md",
            temporal_kind="point_event",
            event_field="event_dt",
            keys=["event_dt"],
            columns={
                "event_dt": {"dtype": "date", "nullable": False},
                "published_at": {"dtype": "datetime", "nullable": False},
            },
        )


@pytest.mark.unit
def test_interval_requires_nullable_valid_to() -> None:
    with pytest.raises(ValidationError, match="valid_to"):
        DatasetSchemaSpec(
            dataset="mart.universe_x",
            layer="lake",
            doc_ref="docs/architecture/derived-datasets.md",
            temporal_kind="interval",
            keys=["universe_id", "valid_from"],
            columns={
                "universe_id": {"dtype": "string", "nullable": False},
                "valid_from": {"dtype": "date", "nullable": False},
                "valid_to": {"dtype": "date", "nullable": False},
            },
        )
