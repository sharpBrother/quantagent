"""PostgreSQL 日行情读取：截止列来自契约，重复键失败。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from quantagent.adapters.postgres.daily_prices import (
    PostgresDailyPriceRepository,
    _row_from_mapping,
)
from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.errors import PriceLookupError


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
                "rationale": "单元测试用的日行情可见性规则说明足够长",
            },
            "pit_recoverable": True,
        }
    )


def _fetched(day: str, code: str, close: str) -> dict[str, object]:
    return {
        "TRADE_DT": day,
        "S_INFO_WINDCODE": code,
        "S_DQ_OPEN": Decimal("1"),
        "S_DQ_HIGH": Decimal("1"),
        "S_DQ_LOW": Decimal("1"),
        "S_DQ_CLOSE": Decimal(close),
        "S_DQ_VOLUME": Decimal("1"),
        "S_DQ_AMOUNT": Decimal("1"),
        "S_DQ_PCTCHANGE": Decimal("0.1"),
    }


@pytest.mark.unit
def test_query_uses_visibility_cutoff_and_closed_bounds() -> None:
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [_fetched("20240102", "000001.SZ", "9.2100")]
    rows = PostgresDailyPriceRepository(conn, contract=_contract()).list_prices(
        as_of=date(2024, 1, 3),
        start=date(2024, 1, 2),
        end=date(2024, 1, 5),
        wind_codes=("000001.SZ",),
    )
    statement, params = cur.execute.call_args.args
    assert '"TRADE_DT" BETWEEN %s AND %s' in statement
    assert '"src_wind"."ASHAREEODPRICES"' in statement
    assert '"S_DQ_ADJHIGH"' in statement
    assert '"S_DQ_ADJLOW"' in statement
    assert '"S_DQ_ADJPRECLOSE"' in statement
    assert params == ("20240102", "20240103", ["000001.SZ"])
    assert rows[0].close == Decimal("9.2100")
    assert rows[0].trade_dt == date(2024, 1, 2)


@pytest.mark.unit
def test_duplicate_key_fails_closed() -> None:
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [
        _fetched("20240102", "000001.SZ", "9.2100"),
        _fetched("20240102", "000001.SZ", "9.3000"),
    ]
    with pytest.raises(PriceLookupError, match="行情键重复"):
        PostgresDailyPriceRepository(conn, contract=_contract()).list_prices(
            as_of=date(2024, 1, 3),
            start=date(2024, 1, 2),
            end=date(2024, 1, 2),
            wind_codes=("000001.SZ",),
        )


@pytest.mark.unit
def test_adjusted_range_columns_enter_daily_price() -> None:
    mapping = _fetched("20240102", "000001.SZ", "9.2100")
    mapping["S_DQ_ADJHIGH"] = Decimal("10.5")
    mapping["S_DQ_ADJLOW"] = Decimal("9.4")
    mapping["S_DQ_ADJPRECLOSE"] = Decimal("9.8")
    row = _row_from_mapping(mapping)
    assert row.adj_high == Decimal("10.5")
    assert row.adj_low == Decimal("9.4")
    assert row.adj_preclose == Decimal("9.8")
    assert row.wind_code == "000001.SZ"
    assert row.trade_dt == date(2024, 1, 2)
