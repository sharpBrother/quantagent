"""截止到截面日的最近 N 个交易日。

调用方应先按 ``as_of`` 滤掉不可见行。这里不补日历空档，也不做均值或标准差。
可见日和 ``pit_grade`` 由调用方用返回的这些行推导。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.domain.errors import FeatureLookupError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import date


def last_n_trading_days[T](
    rows: Sequence[T],
    *,
    event_dt: date,
    count: int,
    trade_dt: Callable[[T], date],
) -> tuple[T, ...] | None:
    """返回某一资产在 ``event_dt`` 及之前的最近 ``count`` 个交易日。

    截面日自己没有记录，或更早的交易日不足 ``count`` 个，返回 ``None``。
    同一天出现两行则失败，不挑选其中一行。
    """
    if count < 1:
        raise FeatureLookupError(f"交易日窗口必须 >= 1: {count}")
    chosen: list[T] = []
    seen: set[date] = set()
    for row in rows:
        day = trade_dt(row)
        if day > event_dt:
            continue
        if day in seen:
            raise FeatureLookupError(f"交易日重复: {day.isoformat()}")
        seen.add(day)
        chosen.append(row)
    chosen.sort(key=trade_dt)
    if not chosen or trade_dt(chosen[-1]) != event_dt or len(chosen) < count:
        return None
    return tuple(chosen[-count:])
