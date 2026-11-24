"""从 ``src_wind.AINDEXVALUATION`` 按 as_of 读取指数估值。

只读 ``PE_TTM`` 与 ``DIVIDEND_YIELD``，需要别的字段时窄扩展。不补缺失行，不按交易日过滤（源表含周末行，
取样交给调用方）。截止列和截止日来自可见性契约。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from psycopg.rows import dict_row

from quantagent.adapters.postgres.sql_types import quote_ident
from quantagent.adapters.postgres.src_dml import assert_src_dml_sql
from quantagent.contracts.loader import load_bundle
from quantagent.domain.errors import MissingVisibilityError, PriceLookupError
from quantagent.domain.index_valuation.types import IndexValuation
from quantagent.domain.prices import normalize_wind_codes, visible_price_bounds

if TYPE_CHECKING:
    from datetime import date

    import psycopg

    from quantagent.contracts.spec import VisibilityContract

DATASET = "src.wind.aindexvaluation"
_YMD_LEN = 8
_COLUMNS = ("TRADE_DT", "S_INFO_WINDCODE", "PE_TTM", "DIVIDEND_YIELD")


class PostgresIndexValuationRepository:
    def __init__(
        self,
        conn: psycopg.Connection[object],
        *,
        contract: VisibilityContract | None = None,
    ) -> None:
        self._conn = conn
        self._contract = contract if contract is not None else load_index_valuation_visibility()

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
        column, visible_start, visible_end = bounds
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                _select_sql(column),
                (_ymd(visible_start), _ymd(visible_end), list(codes)),
            )
            fetched = cur.fetchall()
        return _reject_duplicates(tuple(_row_from_mapping(item) for item in fetched))


def load_index_valuation_visibility() -> VisibilityContract:
    vis = load_bundle().visibilities.get(DATASET)
    if vis is None:
        raise MissingVisibilityError(DATASET)
    return vis


def _select_sql(cutoff_column: str) -> str:
    selected = ", ".join(quote_ident(name) for name in _COLUMNS)
    statement = (
        f"SELECT {selected} "
        f"FROM {quote_ident('src_wind')}.{quote_ident('AINDEXVALUATION')} "
        f"WHERE {quote_ident(cutoff_column)} BETWEEN %s AND %s "
        f"AND {quote_ident('S_INFO_WINDCODE')} = ANY(%s) "
        f"ORDER BY {quote_ident('TRADE_DT')}, {quote_ident('S_INFO_WINDCODE')}"
    )
    return assert_src_dml_sql(statement)


def _row_from_mapping(row: dict[str, object]) -> IndexValuation:
    wind_code = row.get("S_INFO_WINDCODE")
    if not isinstance(wind_code, str) or not wind_code.strip():
        raise PriceLookupError("指数代码为空")
    return IndexValuation(
        trade_dt=_parse_trade_dt(row.get("TRADE_DT")),
        wind_code=wind_code,
        pe_ttm=_decimal(row.get("PE_TTM"), "PE_TTM"),
        dividend_yield=_decimal(row.get("DIVIDEND_YIELD"), "DIVIDEND_YIELD"),
    )


def _reject_duplicates(rows: tuple[IndexValuation, ...]) -> tuple[IndexValuation, ...]:
    seen: set[tuple[date, str]] = set()
    for row in rows:
        key = (row.trade_dt, row.wind_code)
        if key in seen:
            raise PriceLookupError(f"指数估值键重复: {row.wind_code} {row.trade_dt.isoformat()}")
        seen.add(key)
    return rows


def _parse_trade_dt(value: object) -> date:
    if not isinstance(value, str) or len(value) != _YMD_LEN or not value.isdigit():
        raise PriceLookupError(f"TRADE_DT 必须是 YYYYMMDD: {value!r}")
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise PriceLookupError(f"TRADE_DT 不是合法日期: {value!r}") from exc


def _decimal(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise PriceLookupError(f"{field} 不是有限值")
        return value
    raise PriceLookupError(f"{field} 不是数值: {type(value).__name__}")


def _ymd(value: date) -> str:
    return value.strftime("%Y%m%d")
