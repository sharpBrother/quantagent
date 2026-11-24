"""same_day_close 与 source_field：截止列不同；其它规则 fail-closed。"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from quantagent.contracts.spec import VisibilityContract, VisibilitySpec
from quantagent.domain.errors import PitUnsupportedError
from quantagent.domain.pit import (
    is_cutoff_visible,
    is_point_event_visible,
    pit_cutoff,
    resolve_row_visibility,
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


def _source_field_strict() -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": "src.macro.fred_observation_vintage",
            "doc_ref": "docs/domain/pit-rules.md",
            "temporal_kind": "point_event",
            "event_field": "observation_date",
            "visibility": {
                "rule": "source_field",
                "field": "realtime_start",
                "strict": True,
                "grade": "A",
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
def test_source_field_strict_excludes_as_of_day() -> None:
    contract = _source_field_strict()
    as_of = date(2024, 1, 10)
    cutoff = pit_cutoff(contract, as_of=as_of)
    assert cutoff.column == "realtime_start"
    assert cutoff.on_or_before == date(2024, 1, 9)
    assert cutoff.rule == "source_field"
    assert not is_cutoff_visible(value=date(2024, 1, 10), cutoff=cutoff)
    assert is_cutoff_visible(value=date(2024, 1, 9), cutoff=cutoff)
    assert is_cutoff_visible(value=date(2024, 1, 4), cutoff=cutoff)


@pytest.mark.unit
def test_source_field_default_is_not_strict() -> None:
    contract = _source_field()
    assert contract.visibility.strict is False
    cutoff = pit_cutoff(contract, as_of=date(2024, 1, 10))
    assert cutoff.on_or_before == date(2024, 1, 10)
    assert is_cutoff_visible(value=date(2024, 1, 10), cutoff=cutoff)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("rule", "extra"),
    [
        ("same_day_close", {}),
        ("release_calendar", {"calendar": "cn_nbs_release"}),
        ("fixed_lag", {"lag_n": 15, "lag_unit": "calendar_day"}),
    ],
)
def test_strict_is_rejected_for_non_source_field(rule: str, extra: dict[str, object]) -> None:
    payload: dict[str, object] = {
        "rule": rule,
        "grade": "A",
        "rationale": "单元测试用的可见性规则说明必须足够长",
        "strict": True,
        **extra,
    }
    with pytest.raises(ValidationError, match="strict 只允许 source_field"):
        VisibilitySpec.model_validate(payload)


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


def _jydb_money_supply() -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": "src.jydb.ed_moneysupply",
            "doc_ref": "docs/migration/jydb-ingest-plan.md",
            "temporal_kind": "period_with_revision",
            "period_fields": ["EndDate"],
            "visibility": {
                "rule": "source_field",
                "field": "InfoPublDate",
                "date_only": True,
                "fallback_mode": "earliest",
                "grade": "A",
                "rationale": "货币供应取发布日与次月 15 日中较早者",
                "fallback": {
                    "rule": "fixed_lag",
                    "field": "EndDate",
                    "lag_n": 15,
                    "lag_unit": "calendar_day",
                    "grade": "B",
                    "rationale": "次月 15 日是制度性保守可见日",
                },
            },
            "pit_recoverable": True,
        }
    )


@pytest.mark.unit
def test_timestamp_cutoff_is_marked_date_only() -> None:
    contract = VisibilityContract.model_validate(
        {
            "dataset": "src.jydb.c_ed_macroindicatordata",
            "doc_ref": "docs/migration/jydb-ingest-plan.md",
            "temporal_kind": "period_with_revision",
            "period_fields": ["IndicatorCode", "EndDate"],
            "visibility": {
                "rule": "source_field",
                "field": "InfoPublDate",
                "date_only": True,
                "grade": "A",
                "rationale": "发布日期带时刻，按日期比较，当天可见",
            },
            "pit_recoverable": True,
        }
    )
    cutoff = pit_cutoff(contract, as_of=date(2024, 1, 10))
    assert cutoff.column == "InfoPublDate"
    assert cutoff.date_only is True
    assert cutoff.on_or_before == date(2024, 1, 10)
    assert cutoff.fallback is None


@pytest.mark.unit
def test_earliest_fallback_picks_earlier_branch_and_grade() -> None:
    contract = _jydb_money_supply()
    cutoff = pit_cutoff(contract, as_of=date(2024, 2, 20))
    assert cutoff.date_only is True
    assert cutoff.fallback is not None
    assert cutoff.fallback.column == "EndDate"
    assert cutoff.fallback.lag_days == 15
    # 2024-01 月末 + 15 天 = 02-15；发布日 02-12 更早，采用 A。
    primary = resolve_row_visibility(cutoff, primary=date(2024, 2, 12), fallback=date(2024, 1, 31))
    assert (primary.visible_on, primary.grade) == (date(2024, 2, 12), "A")
    # 发布日 02-28 晚于 02-15，采用 B。
    fallback = resolve_row_visibility(cutoff, primary=date(2024, 2, 28), fallback=date(2024, 1, 31))
    assert (fallback.visible_on, fallback.grade) == (date(2024, 2, 15), "B")
    # 发布日为空时只看 fallback。
    missing = resolve_row_visibility(cutoff, primary=None, fallback=date(2024, 1, 31))
    assert (missing.visible_on, missing.grade) == (date(2024, 2, 15), "B")
    assert not primary.is_visible(as_of=date(2024, 2, 11))
    assert primary.is_visible(as_of=date(2024, 2, 12))


@pytest.mark.unit
def test_earliest_fallback_rejects_non_month_end_anchor() -> None:
    cutoff = pit_cutoff(_jydb_money_supply(), as_of=date(2024, 2, 20))
    with pytest.raises(PitUnsupportedError, match="不是月末"):
        resolve_row_visibility(cutoff, primary=None, fallback=date(2024, 1, 30))
