"""same_day_close 与 source_field：截止列不同；其它规则 fail-closed。"""

from __future__ import annotations

from datetime import date

import pytest

from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.errors import PitUnsupportedError
from quantagent.domain.pit import (
    is_cutoff_visible,
    is_point_event_visible,
    pit_cutoff,
    visible_event_on_or_before,
)


def _same_day_close() -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": "std.trade_calendar",
            "doc_ref": "docs/contracts/trade-calendar.md",
            "temporal_kind": "point_event",
            "event_field": "cal_dt",
            "visibility": {
                "rule": "same_day_close",
                "grade": "A",
                "rationale": "单元测试用的可见性规则说明必须足够长",
            },
            "pit_recoverable": True,
        }
    )


def _source_field(*, field: str = "knowledge_dt") -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": "feature.value",
            "doc_ref": "docs/architecture/feature-storage.md",
            "temporal_kind": "point_event",
            "event_field": "event_dt",
            "visibility": {
                "rule": "source_field",
                "field": field,
                "grade": "B",
                "rationale": "单元测试用的可见性规则说明必须足够长",
            },
            "pit_recoverable": True,
        }
    )


def _release_calendar() -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": "mart.macro_cpi",
            "doc_ref": "docs/domain/pit-rules.md",
            "temporal_kind": "point_event",
            "event_field": "period_end",
            "visibility": {
                "rule": "release_calendar",
                "calendar": "cn_nbs_release",
                "grade": "C",
                "rationale": "单元测试用的可见性规则说明必须足够长",
            },
            "pit_recoverable": True,
        }
    )


@pytest.mark.unit
def test_same_day_close_includes_as_of() -> None:
    contract = _same_day_close()
    as_of = date(2026, 9, 16)
    assert visible_event_on_or_before(contract, as_of=as_of) == as_of
    assert is_point_event_visible(contract, event_dt=date(2026, 9, 16), as_of=as_of)
    assert is_point_event_visible(contract, event_dt=date(2026, 9, 15), as_of=as_of)
    assert not is_point_event_visible(contract, event_dt=date(2026, 9, 17), as_of=as_of)
    cutoff = pit_cutoff(contract, as_of=as_of)
    assert cutoff.column == "cal_dt"
    assert cutoff.on_or_before == as_of
    assert cutoff.rule == "same_day_close"
    assert cutoff.grade == "A"


@pytest.mark.unit
def test_source_field_cuts_on_declared_field_not_event_dt() -> None:
    contract = _source_field()
    as_of = date(2024, 1, 10)
    cutoff = pit_cutoff(contract, as_of=as_of)
    assert cutoff.column == "knowledge_dt"
    assert cutoff.column != contract.event_field
    assert cutoff.on_or_before == as_of
    assert cutoff.rule == "source_field"
    assert cutoff.grade == "B"
    assert is_cutoff_visible(value=date(2024, 1, 10), cutoff=cutoff)
    assert is_cutoff_visible(value=date(2024, 1, 4), cutoff=cutoff)
    assert not is_cutoff_visible(value=date(2024, 1, 20), cutoff=cutoff)


@pytest.mark.unit
def test_visible_event_on_or_before_rejects_source_field() -> None:
    contract = _source_field()
    with pytest.raises(PitUnsupportedError, match="event_field"):
        visible_event_on_or_before(contract, as_of=date(2024, 1, 10))
    with pytest.raises(PitUnsupportedError, match="event_field"):
        is_point_event_visible(contract, event_dt=date(2024, 1, 3), as_of=date(2024, 1, 10))


@pytest.mark.unit
def test_unimplemented_rule_is_fail_closed() -> None:
    contract = _release_calendar()
    with pytest.raises(PitUnsupportedError, match="尚未实现"):
        pit_cutoff(contract, as_of=date(2026, 9, 16))
    with pytest.raises(PitUnsupportedError, match="尚未实现"):
        visible_event_on_or_before(contract, as_of=date(2026, 9, 16))


@pytest.mark.unit
def test_source_field_fallback_is_fail_closed() -> None:
    contract = VisibilityContract.model_validate(
        {
            "dataset": "mart.fin_statement",
            "doc_ref": "docs/domain/pit-rules.md",
            "temporal_kind": "period_with_revision",
            "period_fields": ["report_period_end", "statement_type"],
            "visibility": {
                "rule": "source_field",
                "field": "ann_dt",
                "grade": "A",
                "rationale": "单元测试用的可见性规则说明必须足够长",
                "fallback": {
                    "rule": "statutory_deadline",
                    "grade": "B",
                    "rationale": "缺公告日时的推断尚未接入求解器",
                },
            },
            "pit_recoverable": True,
        }
    )
    with pytest.raises(PitUnsupportedError, match="fallback"):
        pit_cutoff(contract, as_of=date(2024, 1, 10))
