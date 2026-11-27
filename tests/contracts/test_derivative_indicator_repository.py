"""DerivativeIndicatorRepository：闭区间、as_of 截断、空结果、不补缺失、键重复拒绝。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from quantagent.adapters.memory.derivative_indicator import MemoryDerivativeIndicatorRepository
from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.derivative_indicator.types import DqMarketValue, MarketValue, Turnover
from quantagent.domain.errors import DerivativeIndicatorLookupError, InvalidQueryError


def _contract() -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": "src.wind.ashareeodderivativeindicator",
            "doc_ref": "docs/contracts/src-wind-first-batch.md",
            "temporal_kind": "point_event",
            "event_field": "TRADE_DT",
            "visibility": {
                "rule": "same_day_close",
                "grade": "A",
                "rationale": "契约测试用的衍生指标可见性规则说明足够长",
            },
            "pit_recoverable": True,
        }
    )


def _turn(day: date, code: str, *, value: str | None = "1.5") -> Turnover:
    return Turnover(
        trade_dt=day,
        wind_code=code,
        turnover=None if value is None else Decimal(value),
    )


def _repo() -> MemoryDerivativeIndicatorRepository:
    rows = (
        _turn(date(2024, 1, 2), "000001.SZ", value="1.1"),
        _turn(date(2024, 1, 3), "000001.SZ", value="1.2"),
        _turn(date(2024, 1, 4), "000001.SZ", value="1.3"),
        _turn(date(2024, 1, 3), "600000.SH", value=None),
    )
    return MemoryDerivativeIndicatorRepository(rows, contract=_contract())


@pytest.mark.contracts
def test_closed_interval_and_as_of_hide_later_rows() -> None:
    rows = _repo().list_turnover(
        as_of=date(2024, 1, 3),
        start=date(2024, 1, 2),
        end=date(2024, 1, 5),
        wind_codes=("600000.SH", "000001.SZ"),
    )
    assert [(row.trade_dt, row.wind_code, row.turnover) for row in rows] == [
        (date(2024, 1, 2), "000001.SZ", Decimal("1.1")),
        (date(2024, 1, 3), "000001.SZ", Decimal("1.2")),
        (date(2024, 1, 3), "600000.SH", None),
    ]


@pytest.mark.contracts
def test_missing_code_and_empty_request_return_no_rows() -> None:
    repo = _repo()
    assert (
        repo.list_turnover(
            as_of=date(2024, 1, 5),
            start=date(2024, 1, 2),
            end=date(2024, 1, 5),
            wind_codes=("999999.SZ",),
        )
        == ()
    )
    assert (
        repo.list_turnover(
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
        repo.list_turnover(
            as_of=date(2024, 1, 2),
            start=date(2024, 1, 4),
            end=date(2024, 1, 5),
            wind_codes=("000001.SZ",),
        )
        == ()
    )
    with pytest.raises(InvalidQueryError):
        repo.list_turnover(
            as_of=date(2024, 1, 5),
            start=date(2024, 1, 5),
            end=date(2024, 1, 2),
            wind_codes=("000001.SZ",),
        )


@pytest.mark.contracts
def test_duplicate_key_is_rejected() -> None:
    repo = MemoryDerivativeIndicatorRepository(
        (_turn(date(2024, 1, 2), "000001.SZ"), _turn(date(2024, 1, 2), "000001.SZ")),
        contract=_contract(),
    )
    with pytest.raises(DerivativeIndicatorLookupError, match="衍生指标键重复"):
        repo.list_turnover(
            as_of=date(2024, 1, 2),
            start=date(2024, 1, 2),
            end=date(2024, 1, 2),
            wind_codes=("000001.SZ",),
        )


def _mv(day: date, code: str, *, value: str | None = "1000.5") -> MarketValue:
    return MarketValue(
        trade_dt=day,
        wind_code=code,
        total_mv=None if value is None else Decimal(value),
    )


@pytest.mark.contracts
def test_market_value_uses_same_visibility_and_keeps_null_rows() -> None:
    repo = MemoryDerivativeIndicatorRepository(
        (),
        contract=_contract(),
        market_values=(
            _mv(date(2024, 1, 2), "000001.SZ", value="100"),
            _mv(date(2024, 1, 3), "000001.SZ", value="200"),
            _mv(date(2024, 1, 4), "000001.SZ", value="300"),
            _mv(date(2024, 1, 3), "600000.SH", value=None),
        ),
    )
    rows = repo.list_market_value(
        as_of=date(2024, 1, 3),
        start=date(2024, 1, 2),
        end=date(2024, 1, 5),
        wind_codes=("600000.SH", "000001.SZ"),
    )
    # as_of 之后的 2024-01-04 不可见；空市值保留为 None，不丢行。
    assert [(row.trade_dt, row.wind_code, row.total_mv) for row in rows] == [
        (date(2024, 1, 2), "000001.SZ", Decimal("100")),
        (date(2024, 1, 3), "000001.SZ", Decimal("200")),
        (date(2024, 1, 3), "600000.SH", None),
    ]


def _dqmv(day: date, code: str, *, value: str | None = "800.5") -> DqMarketValue:
    return DqMarketValue(
        trade_dt=day,
        wind_code=code,
        dq_mv=None if value is None else Decimal(value),
    )


@pytest.mark.contracts
def test_dq_market_value_reads_float_mv_and_keeps_null_rows() -> None:
    repo = MemoryDerivativeIndicatorRepository(
        (),
        contract=_contract(),
        dq_market_values=(
            _dqmv(date(2024, 1, 2), "000001.SZ", value="90"),
            _dqmv(date(2024, 1, 3), "000001.SZ", value="95"),
            _dqmv(date(2024, 1, 4), "000001.SZ", value="97"),
            _dqmv(date(2024, 1, 3), "600000.SH", value=None),
        ),
    )
    rows = repo.list_dq_market_value(
        as_of=date(2024, 1, 3),
        start=date(2024, 1, 2),
        end=date(2024, 1, 5),
        wind_codes=("600000.SH", "000001.SZ"),
    )
    # as_of 之后的 2024-01-04 不可见；流通市值（S_DQ_MV）非总市值；空值保留为 None，不丢行。
    assert [(row.trade_dt, row.wind_code, row.dq_mv) for row in rows] == [
        (date(2024, 1, 2), "000001.SZ", Decimal("90")),
        (date(2024, 1, 3), "000001.SZ", Decimal("95")),
        (date(2024, 1, 3), "600000.SH", None),
    ]


@pytest.mark.contracts
def test_dq_market_value_missing_code_and_duplicate_key() -> None:
    repo = MemoryDerivativeIndicatorRepository(
        (),
        contract=_contract(),
        dq_market_values=(
            _dqmv(date(2024, 1, 2), "000001.SZ"),
            _dqmv(date(2024, 1, 2), "000001.SZ"),
        ),
    )
    assert (
        repo.list_dq_market_value(
            as_of=date(2024, 1, 5),
            start=date(2024, 1, 2),
            end=date(2024, 1, 5),
            wind_codes=("999999.SZ",),
        )
        == ()
    )
    with pytest.raises(DerivativeIndicatorLookupError, match="衍生指标键重复"):
        repo.list_dq_market_value(
            as_of=date(2024, 1, 2),
            start=date(2024, 1, 2),
            end=date(2024, 1, 2),
            wind_codes=("000001.SZ",),
        )


@pytest.mark.contracts
def test_market_value_missing_code_and_duplicate_key() -> None:
    repo = MemoryDerivativeIndicatorRepository(
        (),
        contract=_contract(),
        market_values=(_mv(date(2024, 1, 2), "000001.SZ"), _mv(date(2024, 1, 2), "000001.SZ")),
    )
    assert (
        repo.list_market_value(
            as_of=date(2024, 1, 5),
            start=date(2024, 1, 2),
            end=date(2024, 1, 5),
            wind_codes=("999999.SZ",),
        )
        == ()
    )
    with pytest.raises(DerivativeIndicatorLookupError, match="衍生指标键重复"):
        repo.list_market_value(
            as_of=date(2024, 1, 2),
            start=date(2024, 1, 2),
            end=date(2024, 1, 2),
            wind_codes=("000001.SZ",),
        )
