"""指数估值的内存实现。与 PostgreSQL 适配器使用同一套窗口规则。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.domain.errors import PriceLookupError
from quantagent.domain.prices import normalize_wind_codes, visible_price_bounds

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.index_valuation.types import IndexValuation


class MemoryIndexValuationRepository:
    def __init__(self, rows: Sequence[IndexValuation], *, contract: VisibilityContract) -> None:
        self._rows = tuple(rows)
        self._contract = contract

    def list_valuations(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        wind_codes: tuple[str, ...],
    ) -> tuple[IndexValuation, ...]:
        codes = normalize_wind_codes(wind_codes)
        if codes is None:
            return ()
        bounds = visible_price_bounds(contract=self._contract, as_of=as_of, start=start, end=end)
        if bounds is None:
            return ()
        _column, visible_start, visible_end = bounds
        wanted = set(codes)
        matched = sorted(
            (
                row
                for row in self._rows
                if row.wind_code in wanted and visible_start <= row.trade_dt <= visible_end
            ),
            key=lambda row: (row.trade_dt, row.wind_code),
        )
        seen: set[tuple[date, str]] = set()
        for row in matched:
            key = (row.trade_dt, row.wind_code)
            if key in seen:
                raise PriceLookupError(
                    f"指数估值键重复: {row.wind_code} {row.trade_dt.isoformat()}"
                )
            seen.add(key)
        return tuple(matched)
