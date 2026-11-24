"""从 ``src_jydb.QT_OSIndexQuote`` 按 as_of 读取境外指数收盘。

不补缺失的境外交易日，也不在这里做对齐或收益计算。截止列和截止日来自可见性契约。
``TradingDay`` 是 timestamp，但业务含义是日期，所以按 ``::date`` 比较：契约是
``source_field`` + ``strict``，截止日已经是 ``as_of − 1`` 天，按日期比较既不会把
as_of 当天的行带进来，也不会漏掉当天带时刻的行。截止规则仍由 ``domain.pit`` 求解，
这里不另写一套。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from psycopg.rows import dict_row

from quantagent.adapters.postgres.sql_types import quote_ident
from quantagent.adapters.postgres.src_dml import assert_src_dml_sql
from quantagent.contracts.loader import load_bundle
from quantagent.domain.errors import (
    InvalidQueryError,
    MissingVisibilityError,
    PitUnsupportedError,
    PriceLookupError,
)
from quantagent.domain.overseas_index.types import OverseasIndexClose
from quantagent.domain.pit import pit_cutoff

if TYPE_CHECKING:
    import psycopg

    from quantagent.contracts.spec import VisibilityContract

DATASET = "src.jydb.qt_osindexquote"
CUTOFF_COLUMN = "TradingDay"
_COLUMNS = ("TradingDay", "IndexCode", "ClosePrice")


class PostgresOverseasIndexQuoteRepository:
    def __init__(
        self,
        conn: psycopg.Connection[object],
        *,
        contract: VisibilityContract | None = None,
    ) -> None:
        self._conn = conn
        self._contract = contract if contract is not None else load_overseas_index_visibility()

    def list_closes(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        index_codes: tuple[int, ...],
    ) -> tuple[OverseasIndexClose, ...]:
        codes = normalize_index_codes(index_codes)
        if codes is None:
            return ()
        if start > end:
            raise InvalidQueryError("start 晚于 end")
        cutoff = pit_cutoff(self._contract, as_of=as_of)
        if cutoff.column != CUTOFF_COLUMN:
            # 契约换了截止列而读取映射没跟上，按旧列过滤会悄悄放宽或收紧可见性。
            raise PitUnsupportedError(
                f"{DATASET} 契约截止列 {cutoff.column} 与读取映射 {CUTOFF_COLUMN} 不符"
            )
        if cutoff.fallback is not None:
            # 这里只读主截止列；按 fallback 逐行推断可见日没实现，也不估计。
            raise PitUnsupportedError(f"境外指数读取不支持 fallback 可见性契约: {DATASET}")
        visible_end = min(end, cutoff.on_or_before)
        if start > visible_end:
            return ()
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_select_sql(cutoff.column), (start, visible_end, list(codes)))
            fetched = cur.fetchall()
        rows = tuple(_row_from_mapping(item) for item in fetched)
        return _reject_duplicate_rows(rows)


def load_overseas_index_visibility() -> VisibilityContract:
    bundle = load_bundle()
    vis = bundle.visibilities.get(DATASET)
    if vis is None:
        raise MissingVisibilityError(DATASET)
    return vis


def normalize_index_codes(index_codes: tuple[int, ...]) -> tuple[int, ...] | None:
    """空代码列表表示调用方没有观察域，返回空结果，不扩成全部境外指数。"""
    if not index_codes:
        return None
    cleaned = tuple(index_codes)
    if len(set(cleaned)) != len(cleaned):
        raise InvalidQueryError("index_code 重复")
    return cleaned


def _select_sql(cutoff_column: str) -> str:
    selected = ", ".join(quote_ident(name) for name in _COLUMNS)
    cutoff = quote_ident(cutoff_column)
    statement = (
        f"SELECT {selected} "
        f"FROM {quote_ident('src_jydb')}.{quote_ident('QT_OSIndexQuote')} "
        f"WHERE {cutoff}::date BETWEEN %s AND %s "
        f"AND {quote_ident('IndexCode')} = ANY(%s) "
        f"ORDER BY {quote_ident('IndexCode')}, {cutoff}"
    )
    return assert_src_dml_sql(statement)


def _row_from_mapping(row: dict[str, object]) -> OverseasIndexClose:
    index_code = row.get("IndexCode")
    if not isinstance(index_code, int):
        raise PriceLookupError(f"IndexCode 不是整数: {type(index_code).__name__}")
    return OverseasIndexClose(
        trading_day=_parse_trading_day(row.get("TradingDay")),
        index_code=index_code,
        close=_decimal(row.get("ClosePrice"), "ClosePrice"),
    )


def _reject_duplicate_rows(rows: tuple[OverseasIndexClose, ...]) -> tuple[OverseasIndexClose, ...]:
    seen: set[tuple[int, date]] = set()
    for row in rows:
        key = (row.index_code, row.trading_day)
        if key in seen:
            raise PriceLookupError(
                f"境外指数收盘键重复: {row.index_code} {row.trading_day.isoformat()}"
            )
        seen.add(key)
    return rows


def _parse_trading_day(value: object) -> date:
    # 源列是 timestamp；psycopg 返回 datetime，只取日期部分（源端时分秒都是 0）。
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise PriceLookupError(f"TradingDay 不是日期: {value!r}")


def _decimal(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise PriceLookupError(f"{field} 不是有限值")
        return value
    raise PriceLookupError(f"{field} 不是数值: {type(value).__name__}")
