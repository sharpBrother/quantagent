"""境外指数收盘的内存实现。与 PostgreSQL 适配器使用同一套窗口与截止规则。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.domain.errors import InvalidQueryError, PitUnsupportedError, PriceLookupError
from quantagent.domain.pit import pit_cutoff

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.overseas_index.types import OverseasIndexClose

CUTOFF_COLUMN = "TradingDay"


class MemoryOverseasIndexQuoteRepository:
    def __init__(
        self,
        rows: Sequence[OverseasIndexClose],
        *,
        contract: VisibilityContract,
    ) -> None:
        self._rows = tuple(rows)
        self._contract = contract

    def list_closes(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        index_codes: tuple[int, ...],
    ) -> tuple[OverseasIndexClose, ...]:
        codes = _normalize_index_codes(index_codes)
        if codes is None:
            return ()
        if start > end:
            raise InvalidQueryError("start 晚于 end")
        cutoff = pit_cutoff(self._contract, as_of=as_of)
        if cutoff.column != CUTOFF_COLUMN:
            raise PitUnsupportedError(
                f"境外指数契约截止列 {cutoff.column} 与内存实现 {CUTOFF_COLUMN} 不符"
            )
        if cutoff.fallback is not None:
            raise PitUnsupportedError("境外指数读取不支持 fallback 可见性契约")
        visible_end = min(end, cutoff.on_or_before)
        if start > visible_end:
            return ()
        wanted = set(codes)
        matched = [
            row
            for row in self._rows
            if row.index_code in wanted and start <= row.trading_day <= visible_end
        ]
        matched.sort(key=lambda row: (row.index_code, row.trading_day))
        return _reject_duplicate_rows(matched)


def _normalize_index_codes(index_codes: tuple[int, ...]) -> tuple[int, ...] | None:
    """空代码列表表示调用方没有观察域，返回空结果，不扩成全部境外指数。"""
    if not index_codes:
        return None
    cleaned = tuple(index_codes)
    if len(set(cleaned)) != len(cleaned):
        raise InvalidQueryError("index_code 重复")
    return cleaned


def _reject_duplicate_rows(rows: list[OverseasIndexClose]) -> tuple[OverseasIndexClose, ...]:
    seen: set[tuple[int, date]] = set()
    for row in rows:
        key = (row.index_code, row.trading_day)
        if key in seen:
            raise PriceLookupError(
                f"境外指数收盘键重复: {row.index_code} {row.trading_day.isoformat()}"
            )
        seen.add(key)
    return tuple(rows)
