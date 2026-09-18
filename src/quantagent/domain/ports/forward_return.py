"""前瞻收益仓储。只取回 as_of 可见的行；evaluation_only，不进训练特征。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date

    from quantagent.domain.forward_return import ForwardReturn


class ForwardReturnRepository(Protocol):
    def scan_window(
        self,
        *,
        as_of: date,
        horizon: str,
        return_kind: str,
        benchmark_id: str,
        start: date,
        end: date,
    ) -> tuple[ForwardReturn, ...]:
        """``[start, end]`` 内、``as_of`` 可见的前瞻收益。窗口按 ``event_dt``。

        无行则 ``EmptyDomainError``。不提供省略 ``as_of`` 的重载。
        """
        ...
