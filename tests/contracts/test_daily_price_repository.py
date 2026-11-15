"""DailyPriceRepository：闭区间、as_of 截断、空结果、不补缺失。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from quantagent.adapters.memory.prices import MemoryDailyPriceRepository
from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.errors import InvalidQueryError, PriceLookupError
from quantagent.domain.prices.types import DailyPrice


def _contract() -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": "src.wind.ashareeodprices",
            "doc_ref": "docs/contracts/src-wind-ashareeodprices.md",
            "temporal_kind": "point_event",
            "event_field": "TRADE_DT",
            "visibility": {
                "rule": "same_day_close",
                "grade": "A",
                "rationale": "契约测试用的日行情可见性规则说明足够长",
            },
            "pit_recoverable": True,
        }
    )


def _price(day: date, code: str, close: str, *, pct: str | None = None) -> DailyPrice:
    return DailyPrice(
        trade_dt=day,
        wind_code=code,
        open=Decimal("1"),
        high=Decimal("1"),
        low=Decimal("1"),
        close=Decimal(close),
        volume=Decimal("1"),
        amount=Decimal("1"),
        pct_change=None if pct is None else Decimal(pct),
    )


def _repo() -> MemoryDailyPriceRepository:
    rows = (
        _price(date(2024, 1, 2), "000001.SZ", "9.21"),
        _price(date(2024, 1, 3), "000001.SZ", "9.20"),
        _price(date(2024, 1, 4), "000001.SZ", "9.11"),
        _price(date(2024, 1, 3), "600000.SH", "6.64", pct=None),
    )
    return MemoryDailyPriceRepository(rows, contract=_contract())


@pytest.mark.contracts
def test_closed_interval_and_as_of_hide_later_rows() -> None:
    rows = _repo().list_prices(
        as_of=date(2024, 1, 3),
        start=date(2024, 1, 2),
        end=date(2024, 1, 5),
        wind_codes=("600000.SH", "000001.SZ"),
    )
    assert [(row.trade_dt, row.wind_code, row.close) for row in rows] == [
        (date(2024, 1, 2), "000001.SZ", Decimal("9.21")),
        (date(2024, 1, 3), "000001.SZ", Decimal("9.20")),
        (date(2024, 1, 3), "600000.SH", Decimal("6.64")),
    ]
    assert rows[2].pct_change is None


@pytest.mark.contracts
def test_missing_code_and_empty_request_return_no_rows() -> None:
    repo = _repo()
    assert (
        repo.list_prices(
            as_of=date(2024, 1, 5),
            start=date(2024, 1, 2),
            end=date(2024, 1, 5),
            wind_codes=("999999.SZ",),
        )
        == ()
    )
    assert (
        repo.list_prices(
            as_of=date(2024, 1, 5),
            start=date(2024, 1, 2),
            end=date(2024, 1, 5),
            wind_codes=(),
        )
        == ()
    )


@pytest.mark.contracts
def test_future_window_is_empty_and_bad_args_fail() -> None:
    repo = _repo()
    assert (
        repo.list_prices(
            as_of=date(2024, 1, 2),
            start=date(2024, 1, 4),
            end=date(2024, 1, 5),
            wind_codes=("000001.SZ",),
        )
        == ()
    )
    with pytest.raises(InvalidQueryError):
        repo.list_prices(
            as_of=date(2024, 1, 5),
            start=date(2024, 1, 5),
            end=date(2024, 1, 2),
            wind_codes=("000001.SZ",),
        )
    with pytest.raises(PriceLookupError, match="行情键重复"):
        MemoryDailyPriceRepository(
            (
                _price(date(2024, 1, 2), "000001.SZ", "9.21"),
                _price(date(2024, 1, 2), "000001.SZ", "9.30"),
            ),
            contract=_contract(),
        ).list_prices(
            as_of=date(2024, 1, 2),
            start=date(2024, 1, 2),
            end=date(2024, 1, 2),
            wind_codes=("000001.SZ",),
        )
