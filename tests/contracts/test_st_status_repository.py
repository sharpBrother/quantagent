"""StStatusRepository：memory 与 PostgreSQL（假连接）对同一组行、同一组查询结果一致。

假连接会按 ``ENTRY_DT <= 参数`` 过滤行，与真实 SQL 的 WHERE 一致，所以两边都只看见
同样的行子集。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from quantagent.adapters.memory.st import MemoryStStatusRepository
from quantagent.adapters.postgres.st import PostgresStStatusRepository
from quantagent.domain.errors import InvalidQueryError
from quantagent.domain.universe import StRow

AS_OF = date(2024, 3, 31)

# (代码, ENTRY_DT, REMOVE_DT)，与 ASHAREST 的 varchar(8) 形态一致。
_RAW: tuple[tuple[str, str, str | None], ...] = (
    ("000001.SZ", "20240110", None),
    ("000002.SZ", "20240101", "20240201"),
    ("000002.SZ", "20240115", "20240301"),  # 与上一行重叠
    ("000003.SZ", "20240201", "20240301"),
    ("000003.SZ", "20240301", None),  # 摘帽后又戴帽
    ("000004.SZ", "20240401", None),  # ENTRY 晚于 AS_OF，两边都不应看见
)


class _FakeCursor:
    def __init__(self, rows: tuple[dict[str, Any], ...]) -> None:
        self._rows = rows
        self._result: list[dict[str, Any]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, statement: str, params: tuple[str, ...]) -> None:
        assert statement.lstrip().upper().startswith("SELECT")
        (cutoff,) = params
        self._result = [row for row in self._rows if row["ENTRY_DT"] <= cutoff]

    def fetchall(self) -> list[dict[str, Any]]:
        return self._result


class _FakeConn:
    def __init__(self, rows: tuple[dict[str, Any], ...]) -> None:
        self._rows = rows

    def cursor(self, row_factory: object = None) -> _FakeCursor:
        return _FakeCursor(self._rows)


def _pg_dicts(raw: tuple[tuple[str, str, str | None], ...]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {"S_INFO_WINDCODE": code, "ENTRY_DT": entry, "REMOVE_DT": remove}
        for code, entry, remove in raw
    )


def _memory_rows(raw: tuple[tuple[str, str, str | None], ...]) -> tuple[StRow, ...]:
    return tuple(
        StRow(
            asset_id=code,
            entry_date=date(int(entry[:4]), int(entry[4:6]), int(entry[6:])),
            remove_date=None
            if remove is None
            else date(int(remove[:4]), int(remove[4:6]), int(remove[6:])),
        )
        for code, entry, remove in raw
    )


def _repos(
    raw: tuple[tuple[str, str, str | None], ...],
) -> tuple[MemoryStStatusRepository, PostgresStStatusRepository]:
    conn: Any = _FakeConn(_pg_dicts(raw))
    return MemoryStStatusRepository(_memory_rows(raw)), PostgresStStatusRepository(conn)


@pytest.mark.contracts
@pytest.mark.parametrize(
    "dt",
    [
        date(2024, 1, 9),  # 早于任何戴帽
        date(2024, 1, 10),  # 000001 戴帽当天
        date(2024, 1, 31),  # 重叠区间中
        date(2024, 2, 1),  # 000002 第一段摘帽当天
        date(2024, 2, 15),  # 000002 仍在第二段
        date(2024, 3, 1),  # 000003 第一段摘帽当天，第二段戴帽当天
        date(2024, 3, 31),  # AS_OF 当日
    ],
)
def test_memory_and_pg_agree_on_every_day(dt: date) -> None:
    memory, pg = _repos(_RAW)
    assert memory.st_codes_at(as_of=AS_OF, dt=dt) == pg.st_codes_at(as_of=AS_OF, dt=dt)


@pytest.mark.contracts
def test_known_answers_match_on_both_adapters() -> None:
    memory, pg = _repos(_RAW)
    for adapter in (memory, pg):
        assert adapter.st_codes_at(as_of=AS_OF, dt=date(2024, 2, 1)) == frozenset(
            {"000001.SZ", "000002.SZ", "000003.SZ"}
        )
        assert adapter.st_codes_at(as_of=AS_OF, dt=date(2024, 3, 1)) == frozenset(
            {"000001.SZ", "000003.SZ"}
        )


@pytest.mark.contracts
def test_empty_day_is_empty_set_on_both_adapters() -> None:
    memory, pg = _repos((("000001.SZ", "20240110", "20240115"),))
    assert memory.st_codes_at(as_of=AS_OF, dt=date(2024, 3, 1)) == frozenset()
    assert pg.st_codes_at(as_of=AS_OF, dt=date(2024, 3, 1)) == frozenset()


@pytest.mark.contracts
def test_dt_after_as_of_is_invalid_on_both_adapters() -> None:
    memory, pg = _repos(_RAW)
    with pytest.raises(InvalidQueryError):
        memory.st_codes_at(as_of=AS_OF, dt=date(2024, 4, 1))
    with pytest.raises(InvalidQueryError):
        pg.st_codes_at(as_of=AS_OF, dt=date(2024, 4, 1))


@pytest.mark.contracts
def test_remove_before_entry_is_invalid_on_both_adapters() -> None:
    raw = (("000001.SZ", "20240110", "20240105"),)
    memory, pg = _repos(raw)
    with pytest.raises(InvalidQueryError):
        memory.st_codes_at(as_of=AS_OF, dt=AS_OF)
    with pytest.raises(InvalidQueryError):
        pg.st_codes_at(as_of=AS_OF, dt=AS_OF)
