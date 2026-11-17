"""PostgreSQL 指数收益读取：截止列来自契约，重复键和非有限值失败。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from quantagent.adapters.postgres.index_returns import (
    PostgresIndexReturnRepository,
    load_index_visibility,
)
from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.errors import PriceLookupError


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
                "rationale": "单元测试用的指数收益可见性规则说明足够长",
            },
            "pit_recoverable": True,
        }
    )


def _fetched(day: str, code: str, pct: Decimal | None) -> dict[str, object]:
    return {
        "TRADE_DT": day,
        "S_INFO_WINDCODE": code,
        "S_DQ_PCTCHANGE": pct,
    }


@pytest.mark.unit
def test_query_uses_visibility_cutoff_and_closed_bounds() -> None:
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [_fetched("20240102", "000985.CSI", Decimal("0.1200"))]
    rows = PostgresIndexReturnRepository(conn, contract=_contract()).list_returns(
        as_of=date(2024, 1, 3),
        start=date(2024, 1, 2),
        end=date(2024, 1, 5),
        wind_codes=("000985.CSI",),
    )
    statement, params = cur.execute.call_args.args
    assert '"TRADE_DT" BETWEEN %s AND %s' in statement
    assert '"src_wind"."AINDEXEODPRICES"' in statement
    assert '"S_DQ_PCTCHANGE"' in statement
    assert params == ("20240102", "20240103", ["000985.CSI"])
    assert rows[0].pct_change == Decimal("0.1200")
    assert rows[0].trade_dt == date(2024, 1, 2)
    assert rows[0].wind_code == "000985.CSI"


@pytest.mark.unit
def test_duplicate_key_and_non_finite_fail_closed() -> None:
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [
        _fetched("20240102", "000985.CSI", Decimal("0.1200")),
        _fetched("20240102", "000985.CSI", Decimal("0.2000")),
    ]
    with pytest.raises(PriceLookupError, match="指数收益键重复"):
        PostgresIndexReturnRepository(conn, contract=_contract()).list_returns(
            as_of=date(2024, 1, 3),
            start=date(2024, 1, 2),
            end=date(2024, 1, 2),
            wind_codes=("000985.CSI",),
        )
    cur.fetchall.return_value = [_fetched("20240102", "000985.CSI", Decimal("NaN"))]
    with pytest.raises(PriceLookupError, match="不是有限值"):
        PostgresIndexReturnRepository(conn, contract=_contract()).list_returns(
            as_of=date(2024, 1, 3),
            start=date(2024, 1, 2),
            end=date(2024, 1, 2),
            wind_codes=("000985.CSI",),
        )


@pytest.mark.unit
def test_visibility_comes_from_the_existing_contract() -> None:
    vis = load_index_visibility()
    assert vis.dataset == "src.wind.aindexeodprices"
    assert vis.event_field == "TRADE_DT"
    assert vis.visibility.rule == "same_day_close"
    assert vis.visibility.grade == "A"
