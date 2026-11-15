"""日行情窗口。截止日来自可见性契约，不在这里写规则名。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.domain.errors import InvalidQueryError
from quantagent.domain.pit import pit_cutoff

if TYPE_CHECKING:
    from datetime import date

    from quantagent.contracts.spec import VisibilityContract


def normalize_wind_codes(wind_codes: tuple[str, ...]) -> tuple[str, ...] | None:
    """空代码列表表示调用方没有观察域，返回空结果，不扩成全市场。"""
    if not wind_codes:
        return None
    cleaned = tuple(code.strip() for code in wind_codes)
    if any(not code for code in cleaned):
        raise InvalidQueryError("wind_code 为空")
    if len(set(cleaned)) != len(cleaned):
        raise InvalidQueryError("wind_code 重复")
    return cleaned


def visible_price_bounds(
    *,
    contract: VisibilityContract,
    as_of: date,
    start: date,
    end: date,
) -> tuple[str, date, date] | None:
    """闭区间与 ``as_of`` 截止的交集。返回截止列和可见日期闭区间。

    整段都在截止日之后时没有可见行。
    """
    if start > end:
        raise InvalidQueryError("start 晚于 end")
    cutoff = pit_cutoff(contract, as_of=as_of)
    visible_end = min(end, cutoff.on_or_before)
    if start > visible_end:
        return None
    return cutoff.column, start, visible_end
