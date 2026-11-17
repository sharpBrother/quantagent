"""ST 状态仓储。只回答"某日哪些代码是 ST"，不物化，也不暴露区间。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date


class StStatusRepository(Protocol):
    def st_codes_at(self, *, as_of: date, dt: date) -> frozenset[str]:
        """``dt`` 当日为 ST 的代码集合，按代码去重。

        ``as_of`` 决定可见性。``dt > as_of`` 抛 ``InvalidQueryError``，且不查库。
        空集合是合法结果，不抛 ``EmptyDomainError``。
        不提供省略 ``as_of`` 的重载。
        """
        ...
