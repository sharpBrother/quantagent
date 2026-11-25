"""就绪计数的 SQL：只 SELECT、按 TRADE_DT 闭区间、截止不得晚于 as_of、TRADE_DT 解析失败即报错。"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from quantagent.adapters.postgres.readiness import PostgresSourceReadinessRepository
from quantagent.domain.errors import InvalidQueryError, PriceLookupError


def _conn(fetched: list[tuple[object, ...]]) -> MagicMock:
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = fetched
    return conn


@pytest.mark.unit
def test_daily_counts_query_is_closed_range_on_trade_dt_without_codes_filter() -> None:
    conn = _conn([("20260120", 5580), ("20260121", 5579)])
    counts = PostgresSourceReadinessRepository(conn).daily_row_counts(
        as_of=date(2026, 1, 21),
        source="ashareeodprices",
        start=date(2026, 1, 1),
        end=date(2026, 1, 21),
        wind_codes=None,
    )
    statement, params = conn.cursor.return_value.__enter__.return_value.execute.call_args.args
    assert 'FROM "src_wind"."ASHAREEODPRICES"' in statement
    assert '"TRADE_DT" BETWEEN %s AND %s' in statement
    assert "S_INFO_WINDCODE" not in statement
    assert statement.strip().startswith("SELECT")
    assert "GROUP BY" in statement
    assert params == ["20260101", "20260121"]
    assert counts == {date(2026, 1, 20): 5580, date(2026, 1, 21): 5579}


@pytest.mark.unit
def test_index_counts_are_restricted_to_benchmark_code() -> None:
    conn = _conn([("20260120", 1)])
    PostgresSourceReadinessRepository(conn).daily_row_counts(
        as_of=date(2026, 1, 21),
        source="aindexeodprices",
        start=date(2026, 1, 20),
        end=date(2026, 1, 21),
        wind_codes=("000985.CSI",),
    )
    statement, params = conn.cursor.return_value.__enter__.return_value.execute.call_args.args
    assert 'FROM "src_wind"."AINDEXEODPRICES"' in statement
    assert '"S_INFO_WINDCODE" = ANY(%s)' in statement
    assert params == ["20260120", "20260121", ["000985.CSI"]]


@pytest.mark.unit
def test_counts_beyond_as_of_are_rejected_before_any_sql() -> None:
    conn = MagicMock()
    with pytest.raises(InvalidQueryError, match="晚于 as_of"):
        PostgresSourceReadinessRepository(conn).daily_row_counts(
            as_of=date(2026, 1, 20),
            source="ashareeodprices",
            start=date(2026, 1, 1),
            end=date(2026, 1, 21),
            wind_codes=None,
        )
    conn.cursor.assert_not_called()


@pytest.mark.unit
def test_empty_codes_tuple_is_rejected_instead_of_counting_everything() -> None:
    conn = MagicMock()
    with pytest.raises(InvalidQueryError, match="wind_codes 为空"):
        PostgresSourceReadinessRepository(conn).daily_row_counts(
            as_of=date(2026, 1, 21),
            source="aindexeodprices",
            start=date(2026, 1, 1),
            end=date(2026, 1, 21),
            wind_codes=(),
        )
    conn.cursor.assert_not_called()


@pytest.mark.unit
def test_unparseable_trade_dt_fails_closed() -> None:
    conn = _conn([("2026-01-20", 10)])
    with pytest.raises(PriceLookupError, match="YYYYMMDD"):
        PostgresSourceReadinessRepository(conn).daily_row_counts(
            as_of=date(2026, 1, 21),
            source="ashareeodprices",
            start=date(2026, 1, 1),
            end=date(2026, 1, 21),
            wind_codes=None,
        )


@pytest.mark.unit
def test_minute_registration_is_read_from_manifest_for_the_dataset() -> None:
    conn = _conn([(date(2026, 1, 20),), (date(2026, 1, 21),)])
    days = PostgresSourceReadinessRepository(conn).registered_minute_days(
        as_of=date(2026, 1, 21), start=date(2026, 1, 1), end=date(2026, 1, 21)
    )
    statement, params = conn.cursor.return_value.__enter__.return_value.execute.call_args.args
    assert "src_minprice.lake_partition" in statement
    assert params == ("ashare_minute_bar", date(2026, 1, 1), date(2026, 1, 21))
    assert days == frozenset({date(2026, 1, 20), date(2026, 1, 21)})
