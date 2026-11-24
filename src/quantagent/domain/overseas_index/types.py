"""境外指数收盘领域类型。不读存储。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal


@dataclass(frozen=True, slots=True)
class OverseasIndexClose:
    """一个境外指数在一个境外交易日的收盘。

    ``index_code`` 是聚源 ``SecuMainAll.InnerCode``（如 3210 = 标普 500），源端没有
    代码文本，映射写死在研究脚本里。``close`` 保持源端精度，缺失就是 ``None``。
    """

    trading_day: date
    index_code: int
    close: Decimal | None
