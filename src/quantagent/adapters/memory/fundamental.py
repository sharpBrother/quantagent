"""财报与分红窄读取的内存实现。与 PostgreSQL 适配器使用同一套可见性与过滤规则，供契约测试对拍。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.domain.errors import InvalidQueryError
from quantagent.domain.pit import pit_cutoff
from quantagent.domain.prices import normalize_wind_codes

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.fundamental.types import (
        DividendRecord,
        IndicatorRecord,
        NetProfitRecord,
    )


def _window(
    contract: VisibilityContract,
    *,
    as_of: date,
    start: date,
    end: date,
) -> tuple[date, date] | None:
    if start > end:
        raise InvalidQueryError("start 晚于 end")
    cutoff = pit_cutoff(contract, as_of=as_of)
    visible_end = min(end, cutoff.on_or_before)
    if start > visible_end:
        return None
    return start, visible_end


class MemoryDividendRepository:
    def __init__(self, rows: Sequence[DividendRecord], *, contract: VisibilityContract) -> None:
        self._rows = tuple(rows)
        self._contract = contract

    def list_dividends(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        wind_codes: tuple[str, ...],
    ) -> tuple[DividendRecord, ...]:
        codes = normalize_wind_codes(wind_codes)
        bounds = _window(self._contract, as_of=as_of, start=start, end=end)
        if codes is None or bounds is None:
            return ()
        lo, hi = bounds
        wanted = set(codes)
        matched = [row for row in self._rows if row.asset_id in wanted and lo <= row.ann_dt <= hi]
        matched.sort(key=lambda row: (row.asset_id, row.report_period, row.ann_dt))
        return tuple(matched)


class MemoryNetProfitRepository:
    """``rows_by_statement`` 以报表类型为键。``NetProfitRecord`` 不带报表类型，过滤只按键取行。"""

    def __init__(
        self,
        rows_by_statement: Mapping[str, Sequence[NetProfitRecord]],
        *,
        contract: VisibilityContract,
    ) -> None:
        self._rows_by_statement = {key: tuple(rows) for key, rows in rows_by_statement.items()}
        self._contract = contract

    def list_net_profits(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        statement_type: str,
        wind_codes: tuple[str, ...],
    ) -> tuple[NetProfitRecord, ...]:
        if not statement_type.strip():
            raise InvalidQueryError("statement_type 为空")
        codes = normalize_wind_codes(wind_codes)
        bounds = _window(self._contract, as_of=as_of, start=start, end=end)
        if codes is None or bounds is None:
            return ()
        lo, hi = bounds
        wanted = set(codes)
        matched = [
            row
            for row in self._rows_by_statement.get(statement_type, ())
            if row.asset_id in wanted and lo <= row.ann_dt <= hi
        ]
        matched.sort(key=lambda row: (row.asset_id, row.report_period, row.ann_dt))
        return tuple(matched)


class MemoryFinancialIndicatorRepository:
    def __init__(self, rows: Sequence[IndicatorRecord], *, contract: VisibilityContract) -> None:
        self._rows = tuple(rows)
        self._contract = contract

    def list_indicator_rows(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        wind_codes: tuple[str, ...],
    ) -> tuple[IndicatorRecord, ...]:
        codes = normalize_wind_codes(wind_codes)
        bounds = _window(self._contract, as_of=as_of, start=start, end=end)
        if codes is None or bounds is None:
            return ()
        lo, hi = bounds
        wanted = set(codes)
        matched = [row for row in self._rows if row.asset_id in wanted and lo <= row.ann_dt <= hi]
        matched.sort(key=lambda row: (row.asset_id, row.report_period, row.ann_dt))
        return tuple(matched)
