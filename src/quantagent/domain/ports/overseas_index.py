"""境外指数日收盘仓储。只取回 as_of 可见的行；不填充。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date

    from quantagent.domain.overseas_index.types import OverseasIndexClose


class OverseasIndexQuoteRepository(Protocol):
    def list_closes(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        index_codes: tuple[int, ...],
    ) -> tuple[OverseasIndexClose, ...]:
        """``[start, end]`` 内、``as_of`` 可见的境外指数收盘。

        可见性按数据集的可见性契约：境外交易日 T 的数据在 T+1 可见，即
        ``TradingDay`` 严格早于 ``as_of``。空代码返回空元组，不扩成全市场。
        不补缺失的交易日，也不按 A 股交易日过滤——境外交易日与 A 股交易日不重合，
        对齐是调用方的事。
        """
        ...
