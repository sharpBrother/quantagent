"""PostgreSQL 财报与分红窄读取。可见性来自各自的契约，``ANN_DT`` 是截止列（源端空公告日不可见）。

只做源镜像投影：不取季末报告期，不去重，不做季度差分或 TTM。这些口径在 ``features.library.fundamental``。
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from psycopg.rows import dict_row

from quantagent.adapters.postgres.sql_types import quote_ident
from quantagent.adapters.postgres.src_dml import assert_src_dml_sql
from quantagent.adapters.postgres.universe import parse_ymd_optional
from quantagent.contracts.loader import load_bundle
from quantagent.domain.errors import InvalidQueryError, MissingVisibilityError
from quantagent.domain.fundamental.types import (
    DividendRecord,
    IndicatorRecord,
    NetProfitRecord,
)
from quantagent.domain.pit import pit_cutoff
from quantagent.domain.prices import normalize_wind_codes

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date

    import psycopg

    from quantagent.contracts.spec import VisibilityContract

DIVIDEND_DATASET = "src.wind.asharedividend"
INCOME_DATASET = "src.wind.ashareincome"
INDICATOR_DATASET = "src.wind.asharefinancialindicator"


def load_fundamental_visibility(dataset: str) -> VisibilityContract:
    vis = load_bundle().visibilities.get(dataset)
    if vis is None:
        raise MissingVisibilityError(dataset)
    return vis


class PostgresDividendRepository:
    def __init__(
        self,
        conn: psycopg.Connection[object],
        *,
        contract: VisibilityContract | None = None,
    ) -> None:
        self._conn = conn
        self._contract = (
            contract if contract is not None else load_fundamental_visibility(DIVIDEND_DATASET)
        )

    def list_dividends(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        wind_codes: tuple[str, ...],
    ) -> tuple[DividendRecord, ...]:
        codes = normalize_wind_codes(wind_codes)
        window = _visible_window(self._contract, as_of=as_of, start=start, end=end)
        if codes is None or window is None:
            return ()
        column, lo, hi = window
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                _select_sql(
                    "ASHAREDIVIDEND",
                    ("S_INFO_WINDCODE", "ANN_DT", "REPORT_PERIOD", "TOT_CASH_DVD"),
                    column,
                ),
                (lo, hi, list(codes)),
            )
            fetched = cur.fetchall()
        return tuple(_dividend_from_mapping(item) for item in fetched)


class PostgresNetProfitRepository:
    def __init__(
        self,
        conn: psycopg.Connection[object],
        *,
        contract: VisibilityContract | None = None,
    ) -> None:
        self._conn = conn
        self._contract = (
            contract if contract is not None else load_fundamental_visibility(INCOME_DATASET)
        )

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
        window = _visible_window(self._contract, as_of=as_of, start=start, end=end)
        if codes is None or window is None:
            return ()
        column, lo, hi = window
        sql = _select_sql(
            "ASHAREINCOME",
            ("S_INFO_WINDCODE", "ANN_DT", "REPORT_PERIOD", "NET_PROFIT_AFTER_DED_NR_LP"),
            column,
            extra_filter=f" AND {quote_ident('STATEMENT_TYPE')} = %s",
        )
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, (lo, hi, list(codes), statement_type))
            fetched = cur.fetchall()
        return tuple(_net_profit_from_mapping(item) for item in fetched)


class PostgresFinancialIndicatorRepository:
    def __init__(
        self,
        conn: psycopg.Connection[object],
        *,
        contract: VisibilityContract | None = None,
    ) -> None:
        self._conn = conn
        self._contract = (
            contract if contract is not None else load_fundamental_visibility(INDICATOR_DATASET)
        )

    def list_indicator_rows(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        wind_codes: tuple[str, ...],
    ) -> tuple[IndicatorRecord, ...]:
        codes = normalize_wind_codes(wind_codes)
        window = _visible_window(self._contract, as_of=as_of, start=start, end=end)
        if codes is None or window is None:
            return ()
        column, lo, hi = window
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                _select_sql(
                    "ASHAREFINANCIALINDICATOR",
                    ("S_INFO_WINDCODE", "ANN_DT", "REPORT_PERIOD"),
                    column,
                ),
                (lo, hi, list(codes)),
            )
            fetched = cur.fetchall()
        return tuple(_indicator_from_mapping(item) for item in fetched)


def _visible_window(
    contract: VisibilityContract,
    *,
    as_of: date,
    start: date,
    end: date,
) -> tuple[str, str, str] | None:
    """``[start, end]`` 与 ``as_of`` 截止的交集，返回 (截止列, 起, 止) 的 YYYYMMDD 字符串。"""
    if start > end:
        raise InvalidQueryError("start 晚于 end")
    cutoff = pit_cutoff(contract, as_of=as_of)
    visible_end = min(end, cutoff.on_or_before)
    if start > visible_end:
        return None
    return cutoff.column, _ymd(start), _ymd(visible_end)


def _select_sql(
    table: str,
    columns: tuple[str, ...],
    cutoff_column: str,
    *,
    extra_filter: str = "",
) -> str:
    cols = ", ".join(quote_ident(name) for name in columns)
    statement = (
        f"SELECT {cols} FROM {quote_ident('src_wind')}.{quote_ident(table)}"
        f" WHERE {quote_ident(cutoff_column)} BETWEEN %s AND %s"
        f" AND {quote_ident('S_INFO_WINDCODE')} = ANY(%s)"
        f"{extra_filter}"
        f" ORDER BY {quote_ident('S_INFO_WINDCODE')}, {quote_ident('REPORT_PERIOD')},"
        f" {quote_ident(cutoff_column)}"
    )
    return assert_src_dml_sql(statement)


def _dividend_from_mapping(row: Mapping[str, object]) -> DividendRecord:
    return DividendRecord(
        asset_id=_asset_id(row),
        ann_dt=_required_ymd(row, "ANN_DT"),
        report_period=_required_ymd(row, "REPORT_PERIOD"),
        tot_cash_dvd=_decimal(row.get("TOT_CASH_DVD"), "TOT_CASH_DVD"),
    )


def _net_profit_from_mapping(row: Mapping[str, object]) -> NetProfitRecord:
    return NetProfitRecord(
        asset_id=_asset_id(row),
        ann_dt=_required_ymd(row, "ANN_DT"),
        report_period=_required_ymd(row, "REPORT_PERIOD"),
        net_profit_after_ded=_decimal(
            row.get("NET_PROFIT_AFTER_DED_NR_LP"), "NET_PROFIT_AFTER_DED_NR_LP"
        ),
    )


def _indicator_from_mapping(row: Mapping[str, object]) -> IndicatorRecord:
    return IndicatorRecord(
        asset_id=_asset_id(row),
        ann_dt=_required_ymd(row, "ANN_DT"),
        report_period=_required_ymd(row, "REPORT_PERIOD"),
    )


def _asset_id(row: Mapping[str, object]) -> str:
    code = row.get("S_INFO_WINDCODE")
    if not isinstance(code, str) or not code.strip():
        raise InvalidQueryError("S_INFO_WINDCODE 为空")
    return code


def _required_ymd(row: Mapping[str, object], field: str) -> date:
    value = parse_ymd_optional(row.get(field), field)
    if value is None:
        raise InvalidQueryError(f"{field} 为空")
    return value


def _decimal(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise InvalidQueryError(f"{field} 不是有限值")
        return value
    raise InvalidQueryError(f"{field} 不是数值: {type(value).__name__}")


def _ymd(value: date) -> str:
    return value.strftime("%Y%m%d")
