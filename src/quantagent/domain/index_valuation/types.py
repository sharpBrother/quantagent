"""指数日频估值。数值保持源端精度，缺失保持为空。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal


@dataclass(frozen=True, slots=True)
class IndexValuation:
    trade_dt: date
    wind_code: str
    # Wind 口径的滚动市盈率；亏损或无定义时源端可能给非正值，读取层原样返回，
    # 是否剔除由研究口径决定（旧仓 ERP 剔除 PE<=0）。
    pe_ttm: Decimal | None
    # Wind 口径股息率（百分数，4.35 表示 4.35%），缺失保持为空。
    dividend_yield: Decimal | None = None
