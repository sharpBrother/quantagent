"""衍生指标仓储。只取回 as_of 可见的换手行；不补缺、不按行情对齐。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date

    from quantagent.domain.derivative_indicator.types import Turnover


class DerivativeIndicatorRepository(Protocol):
    def list_turnover(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        wind_codes: tuple[str, ...],
    ) -> tuple[Turnover, ...]:
        """``[start, end]`` 内、``as_of`` 可见的换手行。
        行集含源表的非交易日行，由调用方按交易日取用。无行则空元组。
        不提供省略 ``as_of`` 的重载，也不按缺失代码补行。
        """
        ...
