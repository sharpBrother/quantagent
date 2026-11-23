"""宏观序列仓储。只取回 as_of 可见的版本；不填充、不跨日对齐。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date

    from quantagent.domain.macro.types import MacroObservation


class MacroRepository(Protocol):
    def list_observations(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        series_ids: tuple[str, ...],
    ) -> tuple[MacroObservation, ...]:
        """``observation_date`` 落在 ``[start, end]`` 内、``as_of`` 时生效的观测。

        每个序列按自己数据集的可见性契约截止；有修订的源返回 ``as_of`` 当时的
        版本，不是当前版本。业务日按源端自己的日历（美债是美国交易日）；海外日频
        数据的跨时区滞后已写在各自契约里（严格早于 ``as_of``）。空序列列表返回空元组。
        """
        ...
