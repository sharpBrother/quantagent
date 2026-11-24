"""IndexValuationRepository：闭区间、as_of 截断、非交易日行原样返回、重复键失败。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from quantagent.adapters.memory.index_valuation import MemoryIndexValuationRepository
from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.errors import PriceLookupError
from quantagent.domain.index_valuation import IndexValuation


def _contract() -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": "src.wind.aindexvaluation",
            "doc_ref": "docs/contracts/src-wind-first-batch.md",
            "temporal_kind": "point_event",
            "event_field": "TRADE_DT",
            "visibility": {
                "rule": "same_day_close",
                "grade": "A",
                "rationale": "契约测试用的指数估值可见性规则说明",
            },
            "pit_recoverable": True,
        }
    )


def _row(day: date, code: str, pe: str | None, dividend_yield: str | None = None) -> IndexValuation:
    return IndexValuation(
        day,
        code,
        None if pe is None else Decimal(pe),
        None if dividend_yield is None else Decimal(dividend_yield),
    )


@pytest.mark.contracts
def test_window_as_of_and_weekend_rows() -> None:
    repo = MemoryIndexValuationRepository(
        (
            _row(date(2024, 1, 5), "000985.CSI", "15.1"),
            _row(date(2024, 1, 6), "000985.CSI", "15.1"),  # 周六，源表确有此类行
            _row(date(2024, 1, 8), "000985.CSI", "-3"),
            _row(date(2024, 1, 8), "000300.SH", None),
        ),
        contract=_contract(),
    )
    rows = repo.list_valuations(
        as_of=date(2024, 1, 6),
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        wind_codes=("000985.CSI", "000300.SH"),
    )
    assert [(r.trade_dt, r.pe_ttm) for r in rows] == [
        (date(2024, 1, 5), Decimal("15.1")),
        (date(2024, 1, 6), Decimal("15.1")),
    ]
    later = repo.list_valuations(
        as_of=date(2024, 1, 8),
        start=date(2024, 1, 8),
        end=date(2024, 1, 8),
        wind_codes=("000985.CSI", "000300.SH"),
    )
    # 非正 PE 与空值原样返回，剔除与否是研究口径。
    assert [(r.wind_code, r.pe_ttm) for r in later] == [
        ("000300.SH", None),
        ("000985.CSI", Decimal("-3")),
    ]
    assert (
        repo.list_valuations(
            as_of=date(2024, 1, 8), start=date(2024, 1, 1), end=date(2024, 1, 8), wind_codes=()
        )
        == ()
    )


@pytest.mark.contracts
def test_dividend_yield_passes_through() -> None:
    repo = MemoryIndexValuationRepository(
        (
            _row(date(2024, 11, 20), "000922.CSI", "9.4918", "4.3497"),
            _row(date(2024, 11, 20), "000985.CSI", "15.2300"),
        ),
        contract=_contract(),
    )
    rows = repo.list_valuations(
        as_of=date(2024, 11, 20),
        start=date(2024, 11, 20),
        end=date(2024, 11, 20),
        wind_codes=("000922.CSI", "000985.CSI"),
    )
    # 股息率原样返回，缺失保持为空，不补 0 也不补前值。
    assert [(r.wind_code, r.dividend_yield) for r in rows] == [
        ("000922.CSI", Decimal("4.3497")),
        ("000985.CSI", None),
    ]


@pytest.mark.contracts
def test_duplicate_key_fails() -> None:
    repo = MemoryIndexValuationRepository(
        (
            _row(date(2024, 1, 5), "000985.CSI", "15.1"),
            _row(date(2024, 1, 5), "000985.CSI", "15.2"),
        ),
        contract=_contract(),
    )
    with pytest.raises(PriceLookupError, match="指数估值键重复"):
        repo.list_valuations(
            as_of=date(2024, 1, 5),
            start=date(2024, 1, 5),
            end=date(2024, 1, 5),
            wind_codes=("000985.CSI",),
        )
