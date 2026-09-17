"""从已写入的源镜像读取原生行。研究 PIT 过滤不在这里做。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psycopg.rows import dict_row

from quantagent.adapters.postgres.sql_types import quote_ident
from quantagent.adapters.postgres.src_dml import assert_src_dml_sql
from quantagent.adapters.postgres.src_targets import TRADE_CAL

if TYPE_CHECKING:
    import psycopg


def scan_trade_cal(conn: psycopg.Connection[Any]) -> list[dict[str, object]]:
    """拷贝 ``src_tushare.trade_cal`` 当前快照。``as_of`` 不在此截断。"""
    spec = TRADE_CAL
    col_sql = ", ".join(quote_ident(name) for name in spec.native_columns)
    order_sql = ", ".join(quote_ident(name) for name in spec.keys)
    statement = (
        f"SELECT {col_sql} FROM {quote_ident(spec.pg_schema)}.{quote_ident(spec.pg_table)} "
        f"ORDER BY {order_sql}"
    )
    assert_src_dml_sql(statement)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(statement)
        return [{name: row[name] for name in spec.native_columns} for row in cur.fetchall()]
