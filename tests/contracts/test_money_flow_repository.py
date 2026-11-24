"""MoneyFlowRepository：闭区间、as_of 截断、空结果、不补缺失、键重复拒绝。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from quantagent.adapters.memory.money_flow import MemoryMoneyFlowRepository
from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.errors import InvalidQueryError, MoneyFlowLookupError
from quantagent.domain.money_flow.types import MoneyFlow


def _contract() -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": "src.wind.asharemoneyflow",
            "doc_ref": "docs/contracts/src-wind-first-batch.md",
            "temporal_kind": "point_event",
            "event_field": "TRADE_DT",
            "visibility": {
                "rule": "same_day_close",
                "grade": "A",
                "rationale": "契约测试用的资金流可见性规则说明足够长",
            },
            "pit_recoverable": True,
        }
    )


def _flow(day: date, code: str, *, small: str | None = "10") -> MoneyFlow:
    value = None if small is None else Decimal(small)
    return MoneyFlow(
        trade_dt=day,
        wind_code=code,
        buy_value_small_order_act=value,
        buy_value_med_order_act=Decimal("1"),
        buy_value_large_order_act=Decimal("2"),
        sell_value_med_order_act=Decimal("3"),
        sell_value_large_order_act=Decimal("4"),
        value_diff_small_trader=Decimal("5"),
        value_diff_med_trader=Decimal("6"),
        value_diff_large_trader=Decimal("7"),
        value_diff_institute=Decimal("8"),
    )


def _repo() -> MemoryMoneyFlowRepository:
    rows = (
        _flow(date(2024, 1, 2), "000001.SZ", small="11"),
        _flow(date(2024, 1, 3), "000001.SZ", small="12"),
        _flow(date(2024, 1, 4), "000001.SZ", small="13"),
        _flow(date(2024, 1, 3), "600000.SH", small=None),
    )
    return MemoryMoneyFlowRepository(rows, contract=_contract())


@pytest.mark.contracts
def test_closed_interval_and_as_of_hide_later_rows() -> None:
    rows = _repo().list_money_flows(
        as_of=date(2024, 1, 3),
        start=date(2024, 1, 2),
        end=date(2024, 1, 5),
        wind_codes=("600000.SH", "000001.SZ"),
    )
    assert [(row.trade_dt, row.wind_code, row.buy_value_small_order_act) for row in rows] == [
        (date(2024, 1, 2), "000001.SZ", Decimal("11")),
        (date(2024, 1, 3), "000001.SZ", Decimal("12")),
        (date(2024, 1, 3), "600000.SH", None),
    ]


@pytest.mark.contracts
def test_missing_code_and_empty_request_return_no_rows() -> None:
    repo = _repo()
    assert (
        repo.list_money_flows(
            as_of=date(2024, 1, 5),
            start=date(2024, 1, 2),
            end=date(2024, 1, 5),
            wind_codes=("999999.SZ",),
        )
        == ()
    )
    assert (
        repo.list_money_flows(
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
        repo.list_money_flows(
            as_of=date(2024, 1, 2),
            start=date(2024, 1, 4),
            end=date(2024, 1, 5),
            wind_codes=("000001.SZ",),
        )
        == ()
    )
    with pytest.raises(InvalidQueryError):
        repo.list_money_flows(
            as_of=date(2024, 1, 5),
            start=date(2024, 1, 5),
            end=date(2024, 1, 2),
            wind_codes=("000001.SZ",),
        )


@pytest.mark.contracts
def test_duplicate_key_is_rejected() -> None:
    repo = MemoryMoneyFlowRepository(
        (_flow(date(2024, 1, 2), "000001.SZ"), _flow(date(2024, 1, 2), "000001.SZ")),
        contract=_contract(),
    )
    with pytest.raises(MoneyFlowLookupError, match="资金流键重复"):
        repo.list_money_flows(
            as_of=date(2024, 1, 2),
            start=date(2024, 1, 2),
            end=date(2024, 1, 2),
            wind_codes=("000001.SZ",),
        )
