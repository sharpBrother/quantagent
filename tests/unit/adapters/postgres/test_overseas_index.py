"""PostgreSQL 境外指数收盘读取：截止按日期比较，重复键和非有限值失败。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from quantagent.adapters.postgres.overseas_index import (
    PostgresOverseasIndexQuoteRepository,
    load_overseas_index_visibility,
)
from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.errors import InvalidQueryError, PriceLookupError


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
                "rationale": "单元测试用的境外指数可见性规则说明足够长",
            },
            "pit_recoverable": True,
        }
    )


def _fetched(day: datetime, code: int, close: Decimal | None) -> dict[str, object]:
    return {"TradingDay": day, "IndexCode": code, "ClosePrice": close}


def _repo(conn: MagicMock, rows: list[dict[str, object]]) -> PostgresOverseasIndexQuoteRepository:
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = rows
    return PostgresOverseasIndexQuoteRepository(conn, contract=_contract())


@pytest.mark.unit
def test_query_uses_visibility_cutoff_and_closed_bounds() -> None:
    conn = MagicMock()
    repo = _repo(conn, [_fetched(datetime(2023, 6, 13), 8676, Decimal("102.5000"))])
    rows = repo.list_closes(
        as_of=date(2023, 6, 15),
        start=date(2023, 6, 12),
        end=date(2023, 6, 20),
        index_codes=(8676,),
    )
    cur = conn.cursor.return_value.__enter__.return_value
    statement, params = cur.execute.call_args.args
    # 契约 strict：截止日是 as_of − 1 天；TradingDay 是 timestamp，按日期比较
    assert '"TradingDay"::date BETWEEN %s AND %s' in statement
    assert '"src_jydb"."QT_OSIndexQuote"' in statement
    assert '"ClosePrice"' in statement
    assert '"IndexCode" = ANY(%s)' in statement
    assert 'ORDER BY "IndexCode", "TradingDay"' in statement
    assert params == (date(2023, 6, 12), date(2023, 6, 14), [8676])
    assert rows[0].trading_day == date(2023, 6, 13)
    assert rows[0].index_code == 8676
    assert rows[0].close == Decimal("102.5000")


@pytest.mark.unit
def test_empty_codes_and_window_after_cutoff_return_no_rows() -> None:
    conn = MagicMock()
    repo = _repo(conn, [])
    assert (
        repo.list_closes(
            as_of=date(2023, 6, 15),
            start=date(2023, 6, 12),
            end=date(2023, 6, 20),
            index_codes=(),
        )
        == ()
    )
    assert (
        repo.list_closes(
            as_of=date(2023, 6, 10),
            start=date(2023, 6, 12),
            end=date(2023, 6, 20),
            index_codes=(8676,),
        )
        == ()
    )
    cur = conn.cursor.return_value.__enter__.return_value
    assert not cur.execute.called


@pytest.mark.unit
def test_duplicate_key_non_finite_and_bad_args_fail_closed() -> None:
    conn = MagicMock()
    repo = _repo(
        conn,
        [
            _fetched(datetime(2023, 6, 13), 8676, Decimal("102.5000")),
            _fetched(datetime(2023, 6, 13), 8676, Decimal("102.6000")),
        ],
    )
    with pytest.raises(PriceLookupError, match="境外指数收盘键重复"):
        repo.list_closes(
            as_of=date(2023, 6, 15),
            start=date(2023, 6, 12),
            end=date(2023, 6, 20),
            index_codes=(8676,),
        )
    repo = _repo(conn, [_fetched(datetime(2023, 6, 13), 8676, Decimal("NaN"))])
    with pytest.raises(PriceLookupError, match="不是有限值"):
        repo.list_closes(
            as_of=date(2023, 6, 15),
            start=date(2023, 6, 12),
            end=date(2023, 6, 20),
            index_codes=(8676,),
        )
    repo = _repo(conn, [])
    with pytest.raises(InvalidQueryError):
        repo.list_closes(
            as_of=date(2023, 6, 15),
            start=date(2023, 6, 20),
            end=date(2023, 6, 12),
            index_codes=(8676,),
        )
    with pytest.raises(InvalidQueryError, match="index_code 重复"):
        repo.list_closes(
            as_of=date(2023, 6, 15),
            start=date(2023, 6, 12),
            end=date(2023, 6, 20),
            index_codes=(8676, 8676),
        )


@pytest.mark.unit
def test_visibility_comes_from_the_existing_contract() -> None:
    vis = load_overseas_index_visibility()
    assert vis.dataset == "src.jydb.qt_osindexquote"
    assert vis.event_field == "TradingDay"
    assert vis.visibility.rule == "source_field"
    assert vis.visibility.field == "TradingDay"
    assert vis.visibility.strict is True
    assert vis.visibility.grade == "A"
