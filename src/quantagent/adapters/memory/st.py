"""``ASHAREST`` 的内存实现。与 PostgreSQL 版同语义，供契约测试与业务层单测使用。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.domain.universe import check_st_as_of, st_codes

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from quantagent.domain.universe import StRow


class MemoryStStatusRepository:
    def __init__(self, rows: Sequence[StRow]) -> None:
        self._rows = tuple(rows)

    def st_codes_at(self, *, as_of: date, dt: date) -> frozenset[str]:
        check_st_as_of(as_of=as_of, dt=dt)
        # 只把 ENTRY_DT <= dt 的行交给判定，与 PG 版的 WHERE 一致。
        return st_codes((row for row in self._rows if row.entry_date <= dt), dt=dt)
