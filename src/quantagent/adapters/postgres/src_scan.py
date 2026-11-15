"""读取源镜像供物化使用。研究 PIT 过滤由日历仓储执行。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from psycopg.rows import dict_row

from quantagent.adapters.postgres.errors import PostgresAdapterError
from quantagent.adapters.postgres.sql_types import quote_ident
from quantagent.adapters.postgres.src_dml import assert_src_dml_sql
from quantagent.adapters.postgres.src_targets import ASHARECALENDAR

if TYPE_CHECKING:
    import psycopg

_YMD_LEN = 8


def scan_trade_cal(conn: psycopg.Connection[Any]) -> list[dict[str, object]]:
    """按 Wind 开市日生成物化所需的日历快照。"""
    spec = ASHARECALENDAR
    statement = (
        'SELECT "S_INFO_EXCHMARKET" AS exchange, "TRADE_DAYS" AS trade_day '
        f"FROM {quote_ident(spec.pg_schema)}.{quote_ident(spec.pg_table)} "
        "ORDER BY exchange, trade_day"
    )
    assert_src_dml_sql(statement)
    open_days: dict[str, set[date]] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(statement)
        for row in cur.fetchall():
            exchange = row["exchange"]
            raw_day = row["trade_day"]
            if not isinstance(exchange, str) or not exchange.strip():
                raise PostgresAdapterError("ASHARECALENDAR 交易所为空")
            if not isinstance(raw_day, str) or len(raw_day) != _YMD_LEN or not raw_day.isdigit():
                raise PostgresAdapterError(f"ASHARECALENDAR 日期非法: {raw_day!r}")
            try:
                day = date.fromisoformat(raw_day)
            except ValueError as exc:
                raise PostgresAdapterError(f"ASHARECALENDAR 日期非法: {raw_day!r}") from exc
            days = open_days.setdefault(exchange, set())
            if day in days:
                raise PostgresAdapterError(f"ASHARECALENDAR 开市日重复: {exchange} {raw_day}")
            days.add(day)

    return [row for exchange, days in open_days.items() for row in _expand_calendar(exchange, days)]


def _expand_calendar(exchange: str, open_days: set[date]) -> list[dict[str, object]]:
    # Wind 给的是开市日集合，只在各交易所自己的覆盖区间内推导闭市日。
    start, end = min(open_days), max(open_days)
    rows: list[dict[str, object]] = []
    previous_open: str | None = None
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        is_open = day in open_days
        cal_date = day.isoformat().replace("-", "")
        rows.append(
            {
                "exchange": exchange,
                "cal_date": cal_date,
                "is_open": int(is_open),
                "pretrade_date": previous_open,
            }
        )
        if is_open:
            previous_open = cal_date
    return rows
