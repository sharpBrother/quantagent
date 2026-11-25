"""输入就绪判定的计数读取：源表每个交易日的行数，以及分钟分区 manifest 的登记日。

只执行 SELECT，连接由调用方组装（只读）。源表的 TRADE_DT 是 ``YYYYMMDD`` 文本，按闭区间
比较即可；分钟 manifest 的 ``trade_date`` 是 date 类型。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, cast

from quantagent.adapters.postgres.sql_types import quote_ident
from quantagent.adapters.postgres.src_dml import assert_src_dml_sql
from quantagent.domain.errors import InvalidQueryError, PriceLookupError

if TYPE_CHECKING:
    import psycopg

    from quantagent.domain.ports.readiness import DailySource

_TABLES: dict[str, str] = {
    "ashareeodprices": "ASHAREEODPRICES",
    "ashareeodderivativeindicator": "ASHAREEODDERIVATIVEINDICATOR",
    "asharemoneyflow": "ASHAREMONEYFLOW",
    "aindexeodprices": "AINDEXEODPRICES",
}
_MINUTE_DATASET = "ashare_minute_bar"
_YMD_LEN = 8


class PostgresSourceReadinessRepository:
    def __init__(self, conn: psycopg.Connection[object]) -> None:
        self._conn = conn

    def daily_row_counts(
        self,
        *,
        as_of: date,
        source: DailySource,
        start: date,
        end: date,
        wind_codes: tuple[str, ...] | None,
    ) -> dict[date, int]:
        if end > as_of:
            raise InvalidQueryError(f"计数区间终点 {end} 晚于 as_of {as_of}")
        if start > end:
            return {}
        table = _TABLES.get(source)
        if table is None:
            raise InvalidQueryError(f"不支持的就绪源: {source}")
        clauses = [f"{quote_ident('TRADE_DT')} BETWEEN %s AND %s"]
        params: list[object] = [_ymd(start), _ymd(end)]
        if wind_codes is not None:
            if not wind_codes:
                raise InvalidQueryError("wind_codes 为空，拒绝统计")
            clauses.append(f"{quote_ident('S_INFO_WINDCODE')} = ANY(%s)")
            params.append(list(wind_codes))
        statement = (
            f"SELECT {quote_ident('TRADE_DT')}, count(*) "
            f"FROM {quote_ident('src_wind')}.{quote_ident(table)} "
            f"WHERE {' AND '.join(clauses)} "
            f"GROUP BY {quote_ident('TRADE_DT')}"
        )
        with self._conn.cursor() as cur:
            cur.execute(assert_src_dml_sql(statement), params)
            fetched = cast("list[tuple[object, int]]", cur.fetchall())
        return {_parse_trade_dt(trade_dt): count for trade_dt, count in fetched}

    def registered_minute_days(self, *, as_of: date, start: date, end: date) -> frozenset[date]:
        if end > as_of:
            raise InvalidQueryError(f"计数区间终点 {end} 晚于 as_of {as_of}")
        if start > end:
            return frozenset()
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT trade_date FROM src_minprice.lake_partition "
                "WHERE dataset = %s AND trade_date BETWEEN %s AND %s",
                (_MINUTE_DATASET, start, end),
            )
            fetched = cast("list[tuple[date]]", cur.fetchall())
        return frozenset(row[0] for row in fetched)


def _ymd(value: date) -> str:
    return value.strftime("%Y%m%d")


def _parse_trade_dt(value: object) -> date:
    if not isinstance(value, str) or len(value) != _YMD_LEN or not value.isdigit():
        raise PriceLookupError(f"TRADE_DT 必须是 YYYYMMDD: {value!r}")
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise PriceLookupError(f"TRADE_DT 不是合法日期: {value!r}") from exc
