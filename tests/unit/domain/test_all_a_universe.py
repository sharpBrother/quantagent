"""all_a 规则池与市值观测过滤。零 IO。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from quantagent.domain.universe import ListingRow, all_a_listed, all_a_members

DT = date(2024, 6, 3)


def _row(
    asset_id: str = "000001.SZ",
    *,
    list_date: date | None = date(2000, 1, 1),
    delist_date: date | None = None,
    exchange_market: str | None = "SZSE",
) -> ListingRow:
    return ListingRow(
        asset_id=asset_id,
        list_date=list_date,
        delist_date=delist_date,
        exchange_market=exchange_market,
    )


@pytest.mark.unit
def test_listed_exactly_365_days_is_not_member() -> None:
    dt = date(2024, 6, 3)
    row = _row(list_date=dt - timedelta(days=365))
    assert "000001.SZ" not in all_a_listed([row], dt=dt)


@pytest.mark.unit
def test_listed_366_days_is_member() -> None:
    dt = date(2024, 6, 3)
    row = _row(list_date=dt - timedelta(days=366))
    assert "000001.SZ" in all_a_listed([row], dt=dt)


@pytest.mark.unit
def test_list_date_null_is_not_member() -> None:
    assert all_a_listed([_row(list_date=None)], dt=DT) == frozenset()


@pytest.mark.unit
def test_delist_day_is_not_member_and_day_before_is_member() -> None:
    delist = date(2024, 6, 3)
    row = _row(delist_date=delist)
    assert "000001.SZ" not in all_a_listed([row], dt=delist)
    assert "000001.SZ" in all_a_listed([row], dt=delist - timedelta(days=1))


@pytest.mark.unit
def test_delist_date_null_stays_member() -> None:
    assert "000001.SZ" in all_a_listed([_row(delist_date=None)], dt=DT)


@pytest.mark.unit
def test_bse_is_not_member() -> None:
    assert all_a_listed([_row("830001.BJ", exchange_market="BSE")], dt=DT) == frozenset()


@pytest.mark.unit
def test_exchange_market_null_is_not_member() -> None:
    assert all_a_listed([_row(exchange_market=None)], dt=DT) == frozenset()


@pytest.mark.unit
def test_code_starting_with_a_is_not_member() -> None:
    assert all_a_listed([_row("A00001.SZ")], dt=DT) == frozenset()


@pytest.mark.unit
def test_observed_filter_removes_unobserved_codes() -> None:
    listings = [_row("000001.SZ"), _row("000002.SZ")]
    members = all_a_members(listings, dt=DT, observed={"000002.SZ"})
    assert [m.asset_id for m in members] == ["000002.SZ"]


@pytest.mark.unit
def test_members_are_sorted_and_carry_pit_fields() -> None:
    listings = [_row("000002.SZ"), _row("000001.SZ")]
    members = all_a_members(listings, dt=DT, observed={"000001.SZ", "000002.SZ"})
    assert [m.asset_id for m in members] == ["000001.SZ", "000002.SZ"]
    member = members[0]
    assert member.universe_id == "all_a"
    assert member.valid_from == DT
    assert member.valid_to == DT
    assert member.knowledge_dt == DT
    assert member.member_weight is None
    assert member.pit_grade == "B"


@pytest.mark.unit
def test_empty_result_returns_empty_tuple() -> None:
    # 空域报错由适配器负责；纯函数只返回空元组。
    assert all_a_members([_row(list_date=None)], dt=DT, observed=set()) == ()
