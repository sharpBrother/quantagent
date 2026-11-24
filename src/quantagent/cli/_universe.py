"""all_a 股票池按截面日取成员的共用逻辑。资金流、前瞻收益等物化 CLI 都用这里，口径保持一致。

口径：不用某一个日期的成员回填整个区间。读取范围取各截面日成员的并集，输出只保留截面日当天属于
all_a 的行。否则区间中途退出 all_a 的股票会丢掉退出前的截面，造成幸存者偏差。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from quantagent.adapters.postgres.universe import PostgresUniverseRepository
from quantagent.domain.universe.all_a import ALL_A_UNIVERSE_ID

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from datetime import date

    import psycopg


class _Keyed(Protocol):
    """带截面日与股票代码的行。只读属性，兼容 frozen dataclass。"""

    @property
    def asset_id(self) -> str: ...

    @property
    def event_dt(self) -> date: ...


def all_a_members_by_day(
    conn: psycopg.Connection[object], *, as_of: date, days: Sequence[date]
) -> dict[date, frozenset[str]]:
    """逐截面日读取 all_a 成员。``as_of`` 决定可见的上市/退市口径，``days`` 决定截面日。"""
    repo = PostgresUniverseRepository(conn)
    return {
        day: frozenset(
            member.asset_id
            for member in repo.members_at(as_of=as_of, dt=day, universe_id=ALL_A_UNIVERSE_ID)
        )
        for day in days
    }


def union_codes(members_by_day: Mapping[date, frozenset[str]]) -> tuple[str, ...]:
    """区间内各截面日 all_a 成员的并集，升序。只决定读哪些股票，不决定产出哪些行。"""
    merged: set[str] = set()
    for members in members_by_day.values():
        merged |= members
    return tuple(sorted(merged))


def in_membership(
    members_by_day: Mapping[date, frozenset[str]],
) -> Callable[[_Keyed], bool]:
    """返回判断函数：行的股票在该行 ``event_dt`` 当天属于 all_a 才为真。

    截面日不在映射里时为假（fail-closed），不猜测成员关系。
    """

    def _keep(row: _Keyed) -> bool:
        return row.asset_id in members_by_day.get(row.event_dt, frozenset())

    return _keep


def keep_rows_in_membership[RowT: _Keyed](
    rows: Sequence[RowT], members_by_day: Mapping[date, frozenset[str]]
) -> tuple[RowT, ...]:
    """只保留截面日当天属于 all_a 的行。"""
    keep = in_membership(members_by_day)
    return tuple(row for row in rows if keep(row))
