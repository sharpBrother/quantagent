"""指数日收益仓储。只取回 as_of 可见的行；不填充。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date

    from quantagent.domain.index_returns.types import IndexReturn


class IndexReturnRepository(Protocol):
    def list_returns(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        wind_codes: tuple[str, ...],
    ) -> tuple[IndexReturn, ...]:
        """``[start, end]`` 内、``as_of`` 可见的指数涨跌幅。

        空代码返回空元组，不扩成全市场。不提供省略 ``as_of`` 的重载，
        也不按缺失代码或缺失交易日补行。
        """
        ...
