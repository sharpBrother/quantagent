"""从 ``src_wind.ASHAREMONEYFLOW`` 按 as_of 读取资金流。
只做源镜像投影：不补缺失行，不与行情对齐。截止列和截止日来自可见性契约。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from psycopg.rows import dict_row

from quantagent.adapters.postgres.sql_types import quote_ident
from quantagent.adapters.postgres.src_dml import assert_src_dml_sql
from quantagent.contracts.loader import load_bundle
from quantagent.domain.errors import MissingVisibilityError, MoneyFlowLookupError
from quantagent.domain.money_flow.types import MoneyFlow
from quantagent.domain.prices import normalize_wind_codes, visible_price_bounds

if TYPE_CHECKING:
    from datetime import date

    import psycopg

    from quantagent.contracts.spec import VisibilityContract

DATASET = "src.wind.asharemoneyflow"

# 与 MoneyFlow 字段一一对应，顺序即 SELECT 列顺序。
_VALUE_COLUMNS: dict[str, str] = {
    "buy_value_small_order_act": "BUY_VALUE_SMALL_ORDER_ACT",
    "buy_value_med_order_act": "BUY_VALUE_MED_ORDER_ACT",
    "buy_value_large_order_act": "BUY_VALUE_LARGE_ORDER_ACT",
    "sell_value_med_order_act": "SELL_VALUE_MED_ORDER_ACT",
    "sell_value_large_order_act": "SELL_VALUE_LARGE_ORDER_ACT",
    "value_diff_small_trader": "VALUE_DIFF_SMALL_TRADER",
    "value_diff_med_trader": "VALUE_DIFF_MED_TRADER",
    "value_diff_large_trader": "VALUE_DIFF_LARGE_TRADER",
    "value_diff_institute": "VALUE_DIFF_INSTITUTE",
}

_YMD_LEN = 8


class PostgresMoneyFlowRepository:
    def __init__(
        self,
        conn: psycopg.Connection[object],
        *,
        contract: VisibilityContract | None = None,
    ) -> None:
        self._conn = conn
        self._contract = contract if contract is not None else load_money_flow_visibility()

    def list_money_flows(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        wind_codes: tuple[str, ...],
    ) -> tuple[MoneyFlow, ...]:
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
        return _reject_duplicate_money_flows(rows)


def load_money_flow_visibility() -> VisibilityContract:
    bundle = load_bundle()
    vis = bundle.visibilities.get(DATASET)
    if vis is None:
        raise MissingVisibilityError(DATASET)
    return vis


def _select_sql(cutoff_column: str) -> str:
    selected = ", ".join(
        quote_ident(name) for name in ("TRADE_DT", "S_INFO_WINDCODE", *_VALUE_COLUMNS.values())
    )
    statement = (
        f"SELECT {selected} "
        f"FROM {quote_ident('src_wind')}.{quote_ident('ASHAREMONEYFLOW')} "
        f"WHERE {quote_ident(cutoff_column)} BETWEEN %s AND %s "
        f"AND {quote_ident('S_INFO_WINDCODE')} = ANY(%s) "
        f"ORDER BY {quote_ident('TRADE_DT')}, {quote_ident('S_INFO_WINDCODE')}"
    )
    return assert_src_dml_sql(statement)


def _row_from_mapping(row: dict[str, object]) -> MoneyFlow:
    wind_code = row.get("S_INFO_WINDCODE")
    if not isinstance(wind_code, str) or not wind_code.strip():
        raise MoneyFlowLookupError("资金流代码为空")
    values = {field: _decimal(row.get(source), source) for field, source in _VALUE_COLUMNS.items()}
    return MoneyFlow(trade_dt=_parse_trade_dt(row.get("TRADE_DT")), wind_code=wind_code, **values)


def _reject_duplicate_money_flows(rows: tuple[MoneyFlow, ...]) -> tuple[MoneyFlow, ...]:
    seen: set[tuple[date, str]] = set()
    for row in rows:
        key = (row.trade_dt, row.wind_code)
        if key in seen:
            raise MoneyFlowLookupError(f"资金流键重复: {row.wind_code} {row.trade_dt.isoformat()}")
        seen.add(key)
    return rows


def _parse_trade_dt(value: object) -> date:
    if not isinstance(value, str) or len(value) != _YMD_LEN or not value.isdigit():
        raise MoneyFlowLookupError(f"TRADE_DT 必须是 YYYYMMDD: {value!r}")
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise MoneyFlowLookupError(f"TRADE_DT 不是合法日期: {value!r}") from exc


def _decimal(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise MoneyFlowLookupError(f"{field} 不是有限值")
        return value
    raise MoneyFlowLookupError(f"{field} 不是数值: {type(value).__name__}")


def _ymd(value: date) -> str:
    return value.strftime("%Y%m%d")
