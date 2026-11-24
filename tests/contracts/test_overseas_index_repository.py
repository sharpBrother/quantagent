"""OverseasIndexQuoteRepository：闭区间、次日可见（严格早于 as_of）、空代码、不补缺失。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from quantagent.adapters.memory.overseas_index import MemoryOverseasIndexQuoteRepository
from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.errors import InvalidQueryError, PriceLookupError
from quantagent.domain.overseas_index.types import OverseasIndexClose


def _contract() -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": "src.jydb.qt_osindexquote",
            "doc_ref": "docs/adr/2026-11-23-overseas-daily-next-day.md",
            "temporal_kind": "point_event",
            "event_field": "TradingDay",
            "visibility": {
                "rule": "source_field",
                "field": "TradingDay",
                "strict": True,
                "grade": "A",
                "rationale": "契约测试用的境外指数可见性规则说明足够长",
            },
            "pit_recoverable": True,
        }
    )


def _row(day: date, code: int, close: str | None) -> OverseasIndexClose:
    return OverseasIndexClose(
        trading_day=day,
        index_code=code,
        close=None if close is None else Decimal(close),
    )


def _repo() -> MemoryOverseasIndexQuoteRepository:
    rows = (
        _row(date(2024, 1, 2), 8676, "101.5000"),
        _row(date(2024, 1, 3), 8676, "102.0000"),
        _row(date(2024, 1, 5), 8676, "102.5000"),
        _row(date(2024, 1, 3), 3210, None),
    )
    return MemoryOverseasIndexQuoteRepository(rows, contract=_contract())


@pytest.mark.contracts
def test_next_day_visibility_hides_the_as_of_trading_day() -> None:
    # as_of = 2024-01-03：契约 strict，2024-01-03 当天的境外收盘要到次日才可见
    rows = _repo().list_closes(
        as_of=date(2024, 1, 3),
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        index_codes=(3210, 8676),
    )
    assert [(row.trading_day, row.index_code, row.close) for row in rows] == [
        (date(2024, 1, 2), 8676, Decimal("101.5000")),
    ]
    rows = _repo().list_closes(
        as_of=date(2024, 1, 4),
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        index_codes=(3210, 8676),
    )
    assert [(row.trading_day, row.index_code) for row in rows] == [
        (date(2024, 1, 3), 3210),
        (date(2024, 1, 2), 8676),
        (date(2024, 1, 3), 8676),
    ]


@pytest.mark.contracts
def test_closed_interval_and_missing_code_return_no_rows() -> None:
    repo = _repo()
    rows = repo.list_closes(
        as_of=date(2024, 1, 10),
        start=date(2024, 1, 3),
        end=date(2024, 1, 5),
        index_codes=(8676,),
    )
    assert [row.trading_day for row in rows] == [date(2024, 1, 3), date(2024, 1, 5)]
    assert (
        repo.list_closes(
            as_of=date(2024, 1, 10),
            start=date(2024, 1, 3),
            end=date(2024, 1, 5),
            index_codes=(744056,),
        )
        == ()
    )


@pytest.mark.contracts
def test_empty_codes_future_window_and_bad_args() -> None:
    repo = _repo()
    assert (
        repo.list_closes(
            as_of=date(2024, 1, 10),
            start=date(2024, 1, 3),
            end=date(2024, 1, 5),
            index_codes=(),
        )
        == ()
    )
    assert (
        repo.list_closes(
            as_of=date(2024, 1, 2),
            start=date(2024, 1, 3),
            end=date(2024, 1, 5),
            index_codes=(8676,),
        )
        == ()
    )
    with pytest.raises(InvalidQueryError):
        repo.list_closes(
            as_of=date(2024, 1, 10),
            start=date(2024, 1, 5),
            end=date(2024, 1, 3),
            index_codes=(8676,),
        )
    with pytest.raises(InvalidQueryError, match="index_code 重复"):
        repo.list_closes(
            as_of=date(2024, 1, 10),
            start=date(2024, 1, 3),
            end=date(2024, 1, 5),
            index_codes=(8676, 8676),
        )
    with pytest.raises(PriceLookupError, match="境外指数收盘键重复"):
        MemoryOverseasIndexQuoteRepository(
            (
                _row(date(2024, 1, 2), 8676, "101.5000"),
                _row(date(2024, 1, 2), 8676, "101.6000"),
            ),
            contract=_contract(),
        ).list_closes(
            as_of=date(2024, 1, 5),
            start=date(2024, 1, 1),
            end=date(2024, 1, 31),
            index_codes=(8676,),
        )
