"""资金流仓储。只取回 as_of 可见的行；不补缺、不按行情对齐。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date

    from quantagent.domain.money_flow.types import MoneyFlow


class MoneyFlowRepository(Protocol):
    def list_money_flows(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        wind_codes: tuple[str, ...],
    ) -> tuple[MoneyFlow, ...]:
        """``[start, end]`` 内、``as_of`` 可见的资金流。
        无行则空元组。不提供省略 ``as_of`` 的重载，也不按缺失代码补行。
        """
        ...
