"""因子分组净值仓储。只取回 as_of 可见的行；不回测。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date

    from quantagent.domain.group_nav import GroupNav


class GroupNavRepository(Protocol):
    def scan_window(
        self,
        *,
        as_of: date,
        feature_id: str,
        definition_version: str,
        param_hash: str,
        universe_id: str,
        horizon: str,
        run_id: str,
        start: date,
        end: date,
    ) -> tuple[GroupNav, ...]:
        """``[start, end]`` 内、``as_of`` 可见的分组净值。窗口按 ``event_dt``。

        无行则 ``EmptyDomainError``。不提供省略 ``as_of`` 的重载。
        """
        ...
