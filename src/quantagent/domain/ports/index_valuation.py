"""指数估值仓储。只取回 as_of 可见的行；不填充。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date

    from quantagent.domain.index_valuation.types import IndexValuation


class IndexValuationRepository(Protocol):
    def list_valuations(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        wind_codes: tuple[str, ...],
    ) -> tuple[IndexValuation, ...]:
        """``[start, end]`` 内、``as_of`` 可见的指数估值。

        源表含非交易日行（Wind 在周末也出估值），这里原样返回；按交易日取样是
        调用方的事。空代码返回空元组，不扩成全市场；不提供省略 ``as_of`` 的重载。
        """
        ...
