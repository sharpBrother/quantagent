"""ST 当日判定：左闭右开、去重、空结果与校验失败。零外部依赖。"""

from __future__ import annotations

from datetime import date

import pytest

from quantagent.domain.errors import InvalidQueryError
from quantagent.domain.universe import ST_PIT_GRADE, StRow, check_st_as_of, st_codes

_CODE = "000001.SZ"


@pytest.mark.unit
def test_capped_day_is_st() -> None:
    rows = [StRow(_CODE, entry_date=date(2024, 1, 10), remove_date=None)]
    assert st_codes(rows, dt=date(2024, 1, 10)) == frozenset({_CODE})


@pytest.mark.unit
def test_removed_day_is_not_st() -> None:
    rows = [StRow(_CODE, entry_date=date(2024, 1, 10), remove_date=date(2024, 2, 1))]
    assert st_codes(rows, dt=date(2024, 2, 1)) == frozenset()


@pytest.mark.unit
def test_day_before_removal_is_st() -> None:
    rows = [StRow(_CODE, entry_date=date(2024, 1, 10), remove_date=date(2024, 2, 1))]
    assert st_codes(rows, dt=date(2024, 1, 31)) == frozenset({_CODE})


@pytest.mark.unit
def test_day_before_entry_is_not_st() -> None:
    rows = [StRow(_CODE, entry_date=date(2024, 1, 10), remove_date=None)]
    assert st_codes(rows, dt=date(2024, 1, 9)) == frozenset()


@pytest.mark.unit
def test_null_remove_date_stays_st_after_entry() -> None:
    rows = [StRow(_CODE, entry_date=date(2020, 1, 1), remove_date=None)]
    assert st_codes(rows, dt=date(2026, 10, 30)) == frozenset({_CODE})


@pytest.mark.unit
def test_overlapping_rows_for_one_code_are_deduplicated_not_rejected() -> None:
    # ST 与 *ST 之间的类型切换会产生重叠区间，结果按代码只出现一次。
    rows = [
        StRow(_CODE, entry_date=date(2020, 1, 1), remove_date=date(2021, 6, 1)),
        StRow(_CODE, entry_date=date(2021, 1, 1), remove_date=None),
        StRow(_CODE, entry_date=date(2021, 3, 1), remove_date=date(2022, 1, 1)),
    ]
    result = st_codes(rows, dt=date(2021, 3, 15))
    assert result == frozenset({_CODE})
    assert len(result) == 1


@pytest.mark.unit
def test_remove_date_before_entry_date_fails() -> None:
    rows = [StRow(_CODE, entry_date=date(2024, 1, 10), remove_date=date(2024, 1, 9))]
    with pytest.raises(InvalidQueryError):
        st_codes(rows, dt=date(2024, 1, 10))


@pytest.mark.unit
def test_blank_code_fails() -> None:
    rows = [StRow("  ", entry_date=date(2024, 1, 10), remove_date=None)]
    with pytest.raises(InvalidQueryError):
        st_codes(rows, dt=date(2024, 1, 10))


@pytest.mark.unit
def test_empty_rows_return_empty_set_not_error() -> None:
    assert st_codes([], dt=date(2024, 1, 10)) == frozenset()


@pytest.mark.unit
def test_no_row_covering_dt_returns_empty_set() -> None:
    rows = [StRow(_CODE, entry_date=date(2024, 1, 10), remove_date=date(2024, 2, 1))]
    assert st_codes(rows, dt=date(2024, 3, 1)) == frozenset()


@pytest.mark.unit
def test_as_of_before_dt_is_invalid() -> None:
    with pytest.raises(InvalidQueryError):
        check_st_as_of(as_of=date(2024, 1, 9), dt=date(2024, 1, 10))


@pytest.mark.unit
def test_as_of_equal_to_dt_is_allowed() -> None:
    check_st_as_of(as_of=date(2024, 1, 10), dt=date(2024, 1, 10))


@pytest.mark.unit
def test_pit_grade_is_b() -> None:
    assert ST_PIT_GRADE == "B"
