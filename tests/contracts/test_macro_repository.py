"""MacroRepository：每个序列按自己的契约截止；有修订的序列返回 as_of 当时的版本。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from quantagent.adapters.memory.macro import MemoryMacroRepository
from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.errors import InvalidQueryError, MissingVisibilityError
from quantagent.domain.macro import MacroVersion


def _same_day_close(dataset: str, field: str) -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": dataset,
            "doc_ref": "docs/migration/macro-source-ingest-plan.md",
            "temporal_kind": "point_event",
            "event_field": field,
            "visibility": {
                "rule": "same_day_close",
                "grade": "A",
                "rationale": "契约测试用的日频收盘可见规则说明",
            },
            "pit_recoverable": True,
        }
    )


def _alfred() -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": "src.macro.fred_observation_vintage",
            "doc_ref": "docs/migration/macro-source-ingest-plan.md",
            "temporal_kind": "period_with_revision",
            "period_fields": ["series_id", "observation_date"],
            "visibility": {
                "rule": "source_field",
                "field": "realtime_start",
                "strict": True,
                "grade": "A",
                "rationale": "契约测试用的 ALFRED 首发版本严格早于 as_of",
            },
            "pit_recoverable": True,
        }
    )


def _point(series: str, day: date, value: str) -> MacroVersion:
    return MacroVersion(series, day, Decimal(value), day, None)


def _repo() -> MemoryMacroRepository:
    versions = (
        _point("cn_cgb_10y", date(2024, 1, 2), "2.55"),
        _point("cn_cgb_10y", date(2024, 1, 3), "2.53"),
        _point("us_ust_10y", date(2024, 1, 2), "3.95"),
        _point("us_ust_10y", date(2024, 1, 3), "3.91"),
        MacroVersion(
            "us_tips_10y", date(2024, 1, 2), Decimal("1.70"), date(2024, 1, 2), date(2024, 1, 3)
        ),
        MacroVersion("us_tips_10y", date(2024, 1, 2), Decimal("1.72"), date(2024, 1, 4), None),
    )
    return MemoryMacroRepository(
        versions,
        contracts={
            "cn_cgb_10y": _same_day_close("src.wind.cbondcurvecnbd", "TRADE_DT"),
            "us_ust_10y": _same_day_close("src.tushare.us_treasury_yield", "trade_date"),
            "us_tips_10y": _alfred(),
        },
    )


def _rows(as_of: date, series: tuple[str, ...]) -> list[tuple[str, date, Decimal | None, date]]:
    rows = _repo().list_observations(
        as_of=as_of, start=date(2024, 1, 1), end=date(2024, 1, 31), series_ids=series
    )
    return [(r.series_id, r.observation_date, r.value, r.knowledge_dt) for r in rows]


@pytest.mark.contracts
def test_same_day_close_series_visible_on_business_day() -> None:
    assert _rows(date(2024, 1, 2), ("cn_cgb_10y", "us_ust_10y")) == [
        ("cn_cgb_10y", date(2024, 1, 2), Decimal("2.55"), date(2024, 1, 2)),
        ("us_ust_10y", date(2024, 1, 2), Decimal("3.95"), date(2024, 1, 2)),
    ]


@pytest.mark.contracts
def test_strict_vintage_series_returns_version_known_before_as_of() -> None:
    # 严格早于 as_of：2024-01-02 首发的版本在 01-02 当天不可见。
    assert _rows(date(2024, 1, 2), ("us_tips_10y",)) == []
    assert _rows(date(2024, 1, 3), ("us_tips_10y",)) == [
        ("us_tips_10y", date(2024, 1, 2), Decimal("1.70"), date(2024, 1, 2)),
    ]
    assert _rows(date(2024, 1, 5), ("us_tips_10y",)) == [
        ("us_tips_10y", date(2024, 1, 2), Decimal("1.72"), date(2024, 1, 4)),
    ]


@pytest.mark.contracts
def test_empty_request_bad_window_and_missing_contract() -> None:
    repo = _repo()
    assert (
        repo.list_observations(
            as_of=date(2024, 1, 5), start=date(2024, 1, 1), end=date(2024, 1, 5), series_ids=()
        )
        == ()
    )
    with pytest.raises(InvalidQueryError):
        repo.list_observations(
            as_of=date(2024, 1, 5),
            start=date(2024, 1, 5),
            end=date(2024, 1, 1),
            series_ids=("cn_cgb_10y",),
        )
    with pytest.raises(MissingVisibilityError):
        MemoryMacroRepository((), contracts={}).list_observations(
            as_of=date(2024, 1, 5),
            start=date(2024, 1, 1),
            end=date(2024, 1, 5),
            series_ids=("cn_cgb_10y",),
        )
