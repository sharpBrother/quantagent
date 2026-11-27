"""衍生指标换手的内存实现。与 PostgreSQL 适配器使用同一套窗口规则。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.domain.errors import DerivativeIndicatorLookupError
from quantagent.domain.prices import normalize_wind_codes, visible_price_bounds

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.derivative_indicator.types import DqMarketValue, MarketValue, Turnover


class MemoryDerivativeIndicatorRepository:
    def __init__(
        self,
        rows: Sequence[Turnover],
        *,
        contract: VisibilityContract,
        market_values: Sequence[MarketValue] = (),
        dq_market_values: Sequence[DqMarketValue] = (),
    ) -> None:
        self._rows = tuple(rows)
        self._market_values = tuple(market_values)
        self._dq_market_values = tuple(dq_market_values)
        self._contract = contract

    def list_turnover(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        wind_codes: tuple[str, ...],
    ) -> tuple[Turnover, ...]:
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
        return _reject_duplicate_turnover(matched)

    def list_market_value(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        wind_codes: tuple[str, ...],
    ) -> tuple[MarketValue, ...]:
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
            for row in self._market_values
            if row.wind_code in wanted and visible_start <= row.trade_dt <= visible_end
        ]
        matched.sort(key=lambda row: (row.trade_dt, row.wind_code))
        seen: set[tuple[date, str]] = set()
        for row in matched:
            key = (row.trade_dt, row.wind_code)
            if key in seen:
                raise DerivativeIndicatorLookupError(
                    f"衍生指标键重复: {row.wind_code} {row.trade_dt.isoformat()}"
                )
            seen.add(key)
        return tuple(matched)

    def list_dq_market_value(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        wind_codes: tuple[str, ...],
    ) -> tuple[DqMarketValue, ...]:
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
            for row in self._dq_market_values
            if row.wind_code in wanted and visible_start <= row.trade_dt <= visible_end
        ]
        matched.sort(key=lambda row: (row.trade_dt, row.wind_code))
        seen: set[tuple[date, str]] = set()
        for row in matched:
            key = (row.trade_dt, row.wind_code)
            if key in seen:
                raise DerivativeIndicatorLookupError(
                    f"衍生指标键重复: {row.wind_code} {row.trade_dt.isoformat()}"
                )
            seen.add(key)
        return tuple(matched)


def _reject_duplicate_turnover(rows: list[Turnover]) -> tuple[Turnover, ...]:
    seen: set[tuple[date, str]] = set()
    for row in rows:
        key = (row.trade_dt, row.wind_code)
        if key in seen:
            raise DerivativeIndicatorLookupError(
                f"衍生指标键重复: {row.wind_code} {row.trade_dt.isoformat()}"
            )
        seen.add(key)
    return tuple(rows)
