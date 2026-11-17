"""指数日收益的内存实现。与 PostgreSQL 适配器使用同一套窗口规则。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.domain.errors import PriceLookupError
from quantagent.domain.prices import normalize_wind_codes, visible_price_bounds

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.index_returns.types import IndexReturn


class MemoryIndexReturnRepository:
    def __init__(
        self,
        rows: Sequence[IndexReturn],
        *,
        contract: VisibilityContract,
    ) -> None:
        self._rows = tuple(rows)
        self._contract = contract

    def list_returns(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        wind_codes: tuple[str, ...],
    ) -> tuple[IndexReturn, ...]:
        codes = normalize_wind_codes(wind_codes)
        if codes is None:
            return ()
        bounds = visible_price_bounds(
            contract=self._contract,
            as_of=as_of,
            start=start,
            end=end,
        )
        if bounds is None:
            return ()
        _column, visible_start, visible_end = bounds
        wanted = set(codes)
        matched = [
            row
            for row in self._rows
            if row.wind_code in wanted and visible_start <= row.trade_dt <= visible_end
        ]
        matched.sort(key=lambda row: (row.trade_dt, row.wind_code))
        return _reject_duplicate_returns(matched)


def _reject_duplicate_returns(rows: list[IndexReturn]) -> tuple[IndexReturn, ...]:
    seen: set[tuple[date, str]] = set()
    for row in rows:
        key = (row.trade_dt, row.wind_code)
        if key in seen:
            raise PriceLookupError(f"指数收益键重复: {row.wind_code} {row.trade_dt.isoformat()}")
        seen.add(key)
    return tuple(rows)
