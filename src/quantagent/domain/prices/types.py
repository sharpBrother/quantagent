"""日行情行。数值保持源端精度，缺失保持为空。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal


@dataclass(frozen=True, slots=True)
class DailyPrice:
    trade_dt: date
    wind_code: str
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: Decimal | None
    amount: Decimal | None
    pct_change: Decimal | None
    limit_up: Decimal | None = None
    limit_down: Decimal | None = None
    adj_close: Decimal | None = None
    adj_high: Decimal | None = None
    adj_low: Decimal | None = None
    adj_preclose: Decimal | None = None
    # 复权开盘价，映射 S_DQ_ADJOPEN。前瞻收益的 open-to-open 收益腿以它为端点价。
    adj_open: Decimal | None = None
    # 交易状态代码，映射 S_DQ_TRADESTATUSCODE。判停牌只看它 == 0，不看价格：
    # 停牌行的 ADJOPEN 取前收盘价，价格本身看不出停牌。代码取值：-1 交易，0 停牌，
    # 1 N（上市首日），2 XD，4 DR。除 0 外都是可交易日。
    # 依据：本地 PG 抽样 2024-01-02、2024-06-28、2025-06-25、2026-03-31 四个交易日，
    # 状态文本为"停牌"、S_DQ_TRADESTATUSCODE=0、S_DQ_VOLUME=0 三组行的代码集合完全一致。
    trade_status_code: int | None = None
