"""日行情仓储。只取回 as_of 可见的行；不复权、不填充。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date

    from quantagent.domain.prices.types import DailyPrice


class DailyPriceRepository(Protocol):
    def list_prices(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        wind_codes: tuple[str, ...],
    ) -> tuple[DailyPrice, ...]:
        """``[start, end]`` 内、``as_of`` 可见的日行情。

        无行则空元组。不提供省略 ``as_of`` 的重载，也不按缺失代码补行。
        """
        ...
