"""IndexReturnRepository：闭区间、as_of 截断、空结果、不补缺失。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from quantagent.adapters.memory.index_returns import MemoryIndexReturnRepository
from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.errors import InvalidQueryError, PriceLookupError
from quantagent.domain.index_returns.types import IndexReturn


def _contract() -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": "src.wind.aindexeodprices",
            "doc_ref": "docs/contracts/src-wind-aindexeodprices.md",
            "temporal_kind": "point_event",
            "event_field": "TRADE_DT",
            "visibility": {
                "rule": "same_day_close",
                "grade": "A",
                "rationale": "契约测试用的指数收益可见性规则说明足够长",
            },
            "pit_recoverable": True,
        }
    )


def _row(day: date, code: str, pct: str | None) -> IndexReturn:
    return IndexReturn(
        trade_dt=day,
        wind_code=code,
        pct_change=None if pct is None else Decimal(pct),
    )


def _repo() -> MemoryIndexReturnRepository:
    rows = (
        _row(date(2024, 1, 2), "000985.CSI", "0.12"),
        _row(date(2024, 1, 3), "000985.CSI", "-0.34"),
        _row(date(2024, 1, 5), "000985.CSI", "0.56"),
        _row(date(2024, 1, 3), "000300.SH", None),
    )
    return MemoryIndexReturnRepository(rows, contract=_contract())


@pytest.mark.contracts
def test_closed_interval_and_as_of_hide_later_rows() -> None:
    rows = _repo().list_returns(
        as_of=date(2024, 1, 3),
        start=date(2024, 1, 2),
        end=date(2024, 1, 6),
        wind_codes=("000300.SH", "000985.CSI"),
    )
    assert [(row.trade_dt, row.wind_code, row.pct_change) for row in rows] == [
        (date(2024, 1, 2), "000985.CSI", Decimal("0.12")),
        (date(2024, 1, 3), "000300.SH", None),
        (date(2024, 1, 3), "000985.CSI", Decimal("-0.34")),
    ]
    assert date(2024, 1, 4) not in {row.trade_dt for row in rows}
    assert date(2024, 1, 5) not in {row.trade_dt for row in rows}


@pytest.mark.contracts
def test_missing_code_and_empty_request_return_no_rows() -> None:
    repo = _repo()
    assert (
        repo.list_returns(
            as_of=date(2024, 1, 5),
            start=date(2024, 1, 2),
            end=date(2024, 1, 5),
            wind_codes=("399300.SZ",),
        )
        == ()
    )
    assert (
        repo.list_returns(
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
        repo.list_returns(
            as_of=date(2024, 1, 2),
            start=date(2024, 1, 4),
            end=date(2024, 1, 5),
            wind_codes=("000985.CSI",),
        )
        == ()
    )
    with pytest.raises(InvalidQueryError):
        repo.list_returns(
            as_of=date(2024, 1, 5),
            start=date(2024, 1, 5),
            end=date(2024, 1, 2),
            wind_codes=("000985.CSI",),
        )
    with pytest.raises(PriceLookupError, match="指数收益键重复"):
        MemoryIndexReturnRepository(
            (
                _row(date(2024, 1, 2), "000985.CSI", "0.12"),
                _row(date(2024, 1, 2), "000985.CSI", "0.20"),
            ),
            contract=_contract(),
        ).list_returns(
            as_of=date(2024, 1, 2),
            start=date(2024, 1, 2),
            end=date(2024, 1, 2),
            wind_codes=("000985.CSI",),
        )
