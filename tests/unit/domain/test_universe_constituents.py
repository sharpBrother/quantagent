"""成分股票池纯函数：universe_id 解析、区间命中、重叠与空 INDATE。零 IO。"""

from __future__ import annotations

from datetime import date

import pytest

from quantagent.domain.errors import InvalidQueryError
from quantagent.domain.universe import (
    CONSTITUENT_FAMILIES,
    ConstituentRow,
    constituent_members,
    parse_constituent_universe_id,
)

DT = date(2024, 1, 31)
UID = "index:000300.SH"


def _row(
    asset_id: str = "000001.SZ",
    *,
    index_code: str = "000300.SH",
    in_date: date | None = date(2020, 1, 1),
    out_date: date | None = None,
) -> ConstituentRow:
    return ConstituentRow(
        index_code=index_code,
        asset_id=asset_id,
        in_date=in_date,
        out_date=out_date,
    )


@pytest.mark.unit
def test_families_are_the_five_declared_names() -> None:
    assert frozenset({"index", "citics1", "citics2", "citics3", "sw"}) == CONSTITUENT_FAMILIES


@pytest.mark.unit
@pytest.mark.parametrize("family", ["index", "citics1", "citics2", "citics3", "sw"])
def test_parse_accepts_each_family(family: str) -> None:
    assert parse_constituent_universe_id(f"{family}:000300.SH") == (family, "000300.SH")


@pytest.mark.unit
@pytest.mark.parametrize(
    "universe_id",
    [
        "all_a",
        "",
        "index",
        "index:",
        "index: ",
        "unknown:000300.SH",
        "INDEX:000300.SH",
        "ALL_A",
    ],
)
def test_parse_rejects_invalid_universe_id(universe_id: str) -> None:
    with pytest.raises(InvalidQueryError):
        parse_constituent_universe_id(universe_id)


@pytest.mark.unit
def test_interval_endpoints_are_closed() -> None:
    rows = [
        _row("A_IN", in_date=DT, out_date=None),
        _row("B_OUT", in_date=date(2020, 1, 1), out_date=DT),
    ]
    members = constituent_members(rows, universe_id=UID, dt=DT)
    assert [m.asset_id for m in members] == ["A_IN", "B_OUT"]


@pytest.mark.unit
def test_out_date_before_dt_is_not_member() -> None:
    rows = [_row(in_date=date(2020, 1, 1), out_date=date(2024, 1, 30))]
    assert constituent_members(rows, universe_id=UID, dt=DT) == ()


@pytest.mark.unit
def test_in_date_after_dt_is_not_member() -> None:
    rows = [_row(in_date=date(2024, 2, 1), out_date=None)]
    assert constituent_members(rows, universe_id=UID, dt=DT) == ()


@pytest.mark.unit
def test_members_carry_interval_fields_and_pit_grade_b() -> None:
    rows = [_row("000002.SZ", in_date=date(2020, 1, 1), out_date=date(2030, 1, 1))]
    (member,) = constituent_members(rows, universe_id=UID, dt=DT)
    assert member.universe_id == UID
    assert member.asset_id == "000002.SZ"
    assert member.valid_from == date(2020, 1, 1)
    assert member.valid_to == date(2030, 1, 1)
    assert member.member_weight is None
    assert member.knowledge_dt == date(2020, 1, 1)
    assert member.pit_grade == "B"


@pytest.mark.unit
def test_members_sorted_by_asset_id() -> None:
    rows = [_row("000002.SZ"), _row("000001.SZ"), _row("600000.SH")]
    members = constituent_members(rows, universe_id=UID, dt=DT)
    assert [m.asset_id for m in members] == ["000001.SZ", "000002.SZ", "600000.SH"]


@pytest.mark.unit
def test_other_index_rows_are_ignored() -> None:
    rows = [_row("000001.SZ", index_code="000905.SH")]
    assert constituent_members(rows, universe_id=UID, dt=DT) == ()


@pytest.mark.unit
def test_empty_rows_return_empty_tuple() -> None:
    assert constituent_members([], universe_id=UID, dt=DT) == ()


@pytest.mark.unit
def test_null_in_date_fails_even_when_row_does_not_cover_dt() -> None:
    rows = [_row("000001.SZ", in_date=None)]
    with pytest.raises(InvalidQueryError, match="S_CON_INDATE"):
        constituent_members(rows, universe_id=UID, dt=DT)


@pytest.mark.unit
def test_same_asset_covered_twice_on_dt_fails_closed() -> None:
    # 与 601058.SH 在 wx2 上的残行同形：两条都未结束，同一天被两行覆盖。
    rows = [
        _row("601058.SH", in_date=date(2025, 2, 6), out_date=None),
        _row("601058.SH", in_date=date(2025, 3, 4), out_date=None),
    ]
    with pytest.raises(InvalidQueryError, match="重叠"):
        constituent_members(rows, universe_id=UID, dt=date(2025, 3, 5))


@pytest.mark.unit
def test_overlap_that_does_not_cover_dt_is_not_an_error() -> None:
    rows = [
        _row("601058.SH", in_date=date(2020, 1, 1), out_date=date(2023, 12, 31)),
        _row("601058.SH", in_date=date(2024, 1, 1), out_date=None),
        _row("601058.SH", in_date=date(2024, 6, 1), out_date=None),
    ]
    members = constituent_members(rows, universe_id=UID, dt=DT)
    assert [m.asset_id for m in members] == ["601058.SH"]
