"""股票池成员仓储。只取回 as_of 可见、dt 当日在池内的成员。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date

    from quantagent.domain.universe import UniverseMember


class UniverseRepository(Protocol):
    def members_at(
        self,
        *,
        as_of: date,
        dt: date,
        universe_id: str,
    ) -> tuple[UniverseMember, ...]:
        """``dt`` 当日在池内、且 ``as_of`` 可见的成员。

        区间条件不暴露给调用方。无行则 ``EmptyDomainError``。
        不提供省略 ``as_of`` 的重载。
        """
        ...
