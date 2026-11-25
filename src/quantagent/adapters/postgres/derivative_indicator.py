"""从 ``src_wind.ASHAREEODDERIVATIVEINDICATOR`` 按 as_of 读取换手率。
只做源镜像投影：不补缺失行，不与行情对齐，不过滤非交易日行（由调用方按交易日取用）。
截止列和截止日来自可见性契约，与 universe 的衍生指标截止共用同一份契约。
SQL 只走 ``TRADE_DT`` 范围条件，0024 迁移给该列建了索引，不做全表扫描。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from psycopg.rows import dict_row

from quantagent.adapters.postgres.sql_types import quote_ident
from quantagent.adapters.postgres.src_dml import assert_src_dml_sql
from quantagent.adapters.postgres.universe import load_derivative_visibility
from quantagent.domain.derivative_indicator.types import MarketValue, Turnover
from quantagent.domain.errors import DerivativeIndicatorLookupError
from quantagent.domain.prices import normalize_wind_codes, visible_price_bounds

if TYPE_CHECKING:
    from datetime import date

    import psycopg

    from quantagent.contracts.spec import VisibilityContract

_YMD_LEN = 8


class PostgresDerivativeIndicatorRepository:
    def __init__(
        self,
        conn: psycopg.Connection[object],
        *,
        contract: VisibilityContract | None = None,
    ) -> None:
        self._conn = conn
        self._contract = contract if contract is not None else load_derivative_visibility()

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
        column, visible_start, visible_end = bounds
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                _select_sql(column),
                (_ymd(visible_start), _ymd(visible_end), list(codes)),
            )
            fetched = cur.fetchall()
        rows = tuple(_row_from_mapping(item) for item in fetched)
        return _reject_duplicate_turnover(rows)

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
        column, visible_start, visible_end = bounds
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                _market_value_select_sql(column),
                (_ymd(visible_start), _ymd(visible_end), list(codes)),
            )
            fetched = cur.fetchall()
        rows = tuple(_market_value_from_mapping(item) for item in fetched)
        _reject_duplicate_market_value(rows)
        return rows


def _market_value_select_sql(cutoff_column: str) -> str:
    statement = (
        f"SELECT {quote_ident('TRADE_DT')}, {quote_ident('S_INFO_WINDCODE')}, "
        f"{quote_ident('S_VAL_MV')} "
        f"FROM {quote_ident('src_wind')}.{quote_ident('ASHAREEODDERIVATIVEINDICATOR')} "
        f"WHERE {quote_ident(cutoff_column)} BETWEEN %s AND %s "
        f"AND {quote_ident('S_INFO_WINDCODE')} = ANY(%s) "
        f"ORDER BY {quote_ident('TRADE_DT')}, {quote_ident('S_INFO_WINDCODE')}"
    )
    return assert_src_dml_sql(statement)


def _market_value_from_mapping(row: dict[str, object]) -> MarketValue:
    wind_code = row.get("S_INFO_WINDCODE")
    if not isinstance(wind_code, str) or not wind_code.strip():
        raise DerivativeIndicatorLookupError("衍生指标代码为空")
    return MarketValue(
        trade_dt=_parse_trade_dt(row.get("TRADE_DT")),
        wind_code=wind_code,
        total_mv=_decimal(row.get("S_VAL_MV"), "S_VAL_MV"),
    )


def _reject_duplicate_market_value(rows: tuple[MarketValue, ...]) -> None:
    seen: set[tuple[date, str]] = set()
    for row in rows:
        key = (row.trade_dt, row.wind_code)
        if key in seen:
            raise DerivativeIndicatorLookupError(
                f"衍生指标键重复: {row.wind_code} {row.trade_dt.isoformat()}"
            )
        seen.add(key)


def _select_sql(cutoff_column: str) -> str:
    statement = (
        f"SELECT {quote_ident('TRADE_DT')}, {quote_ident('S_INFO_WINDCODE')}, "
        f"{quote_ident('S_DQ_TURN')} "
        f"FROM {quote_ident('src_wind')}.{quote_ident('ASHAREEODDERIVATIVEINDICATOR')} "
        f"WHERE {quote_ident(cutoff_column)} BETWEEN %s AND %s "
        f"AND {quote_ident('S_INFO_WINDCODE')} = ANY(%s) "
        f"ORDER BY {quote_ident('TRADE_DT')}, {quote_ident('S_INFO_WINDCODE')}"
    )
    return assert_src_dml_sql(statement)


def _row_from_mapping(row: dict[str, object]) -> Turnover:
    wind_code = row.get("S_INFO_WINDCODE")
    if not isinstance(wind_code, str) or not wind_code.strip():
        raise DerivativeIndicatorLookupError("衍生指标代码为空")
    return Turnover(
        trade_dt=_parse_trade_dt(row.get("TRADE_DT")),
        wind_code=wind_code,
        turnover=_decimal(row.get("S_DQ_TURN"), "S_DQ_TURN"),
    )


def _reject_duplicate_turnover(rows: tuple[Turnover, ...]) -> tuple[Turnover, ...]:
    seen: set[tuple[date, str]] = set()
    for row in rows:
        key = (row.trade_dt, row.wind_code)
        if key in seen:
            raise DerivativeIndicatorLookupError(
                f"衍生指标键重复: {row.wind_code} {row.trade_dt.isoformat()}"
            )
        seen.add(key)
    return rows


def _parse_trade_dt(value: object) -> date:
    if not isinstance(value, str) or len(value) != _YMD_LEN or not value.isdigit():
        raise DerivativeIndicatorLookupError(f"TRADE_DT 必须是 YYYYMMDD: {value!r}")
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise DerivativeIndicatorLookupError(f"TRADE_DT 不是合法日期: {value!r}") from exc


def _decimal(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise DerivativeIndicatorLookupError(f"{field} 不是有限值")
        return value
    raise DerivativeIndicatorLookupError(f"{field} 不是数值: {type(value).__name__}")


def _ymd(value: date) -> str:
    return value.strftime("%Y%m%d")
