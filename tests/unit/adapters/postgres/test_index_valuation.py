"""PostgreSQL 指数估值读取：截止列来自契约，重复键和非有限值失败。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from quantagent.adapters.postgres.index_valuation import (
    PostgresIndexValuationRepository,
    load_index_valuation_visibility,
)
from quantagent.domain.errors import PriceLookupError


def _fetched(
    day: str, code: str, pe: Decimal | None, dividend_yield: Decimal | None = None
) -> dict[str, object]:
    return {
        "TRADE_DT": day,
        "S_INFO_WINDCODE": code,
        "PE_TTM": pe,
        "DIVIDEND_YIELD": dividend_yield,
    }


def _repo(rows: list[dict[str, object]]) -> tuple[PostgresIndexValuationRepository, MagicMock]:
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = rows
    return PostgresIndexValuationRepository(conn), cur


@pytest.mark.unit
def test_query_uses_visibility_cutoff() -> None:
    repo, cur = _repo([_fetched("20240102", "000985.CSI", Decimal("15.2300"))])
    rows = repo.list_valuations(
        as_of=date(2024, 1, 3),
        start=date(2024, 1, 2),
        end=date(2024, 1, 5),
        wind_codes=("000985.CSI",),
    )
    statement, params = cur.execute.call_args.args
    assert '"src_wind"."AINDEXVALUATION"' in statement
    assert '"PE_TTM"' in statement
    assert '"DIVIDEND_YIELD"' in statement
    assert '"TRADE_DT" BETWEEN %s AND %s' in statement
    assert params == ("20240102", "20240103", ["000985.CSI"])
    assert rows[0].pe_ttm == Decimal("15.2300")


@pytest.mark.unit
def test_reads_dividend_yield_verbatim() -> None:
    repo, _cur = _repo([_fetched("20241120", "000922.CSI", Decimal("9.4918"), Decimal("4.3497"))])
    rows = repo.list_valuations(
        as_of=date(2024, 11, 20),
        start=date(2024, 11, 20),
        end=date(2024, 11, 20),
        wind_codes=("000922.CSI",),
    )
    assert rows[0].dividend_yield == Decimal("4.3497")
    assert rows[0].pe_ttm == Decimal("9.4918")

    repo, _cur = _repo([_fetched("20241120", "000985.CSI", Decimal("15.2300"), None)])
    rows = repo.list_valuations(
        as_of=date(2024, 11, 20),
        start=date(2024, 11, 20),
        end=date(2024, 11, 20),
        wind_codes=("000985.CSI",),
    )
    assert rows[0].dividend_yield is None


@pytest.mark.unit
def test_duplicate_and_non_finite_fail() -> None:
    repo, _cur = _repo(
        [
            _fetched("20240102", "000985.CSI", Decimal(1)),
            _fetched("20240102", "000985.CSI", Decimal(2)),
        ]
    )
    with pytest.raises(PriceLookupError, match="指数估值键重复"):
        repo.list_valuations(
            as_of=date(2024, 1, 3),
            start=date(2024, 1, 2),
            end=date(2024, 1, 2),
            wind_codes=("000985.CSI",),
        )
    repo, _cur = _repo([_fetched("20240102", "000985.CSI", Decimal("NaN"))])
    with pytest.raises(PriceLookupError, match="不是有限值"):
        repo.list_valuations(
            as_of=date(2024, 1, 3),
            start=date(2024, 1, 2),
            end=date(2024, 1, 2),
            wind_codes=("000985.CSI",),
        )
    repo, _cur = _repo([_fetched("20240102", "000985.CSI", Decimal(1), Decimal("NaN"))])
    with pytest.raises(PriceLookupError, match="不是有限值"):
        repo.list_valuations(
            as_of=date(2024, 1, 3),
            start=date(2024, 1, 2),
            end=date(2024, 1, 2),
            wind_codes=("000985.CSI",),
        )


@pytest.mark.unit
def test_visibility_comes_from_existing_contract() -> None:
    vis = load_index_valuation_visibility()
    assert vis.dataset == "src.wind.aindexvaluation"
    assert vis.visibility.rule == "same_day_close"
