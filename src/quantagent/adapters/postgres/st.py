"""PostgreSQL ST 状态读取。判定规则在 ``domain.universe.st``。

这里每次按日读取 ``src_wind."ASHAREST"`` 中 ``ENTRY_DT <= dt`` 的行，不物化、不写任何表。
``ENTRY_DT`` 与 ``REMOVE_DT`` 是 ``varchar(8)``，日期解析复用 ``universe`` 的
``parse_ymd_optional``，与其他股票池读取保持一致。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from psycopg.rows import dict_row

from quantagent.adapters.postgres.sql_types import quote_ident
from quantagent.adapters.postgres.src_dml import assert_src_dml_sql
from quantagent.adapters.postgres.universe import parse_ymd_optional
from quantagent.domain.errors import InvalidQueryError
from quantagent.domain.universe import StRow, check_st_as_of, st_codes

if TYPE_CHECKING:
    from datetime import date

    import psycopg

_YMD_FORMAT = "%Y%m%d"

_ST_SQL = assert_src_dml_sql(
    "SELECT "
    + ", ".join(quote_ident(name) for name in ("S_INFO_WINDCODE", "ENTRY_DT", "REMOVE_DT"))
    + f" FROM {quote_ident('src_wind')}.{quote_ident('ASHAREST')}"
    # 带上 ENTRY_DT 为 NULL 的行：坏行要在解析时报错，不能被 WHERE 静默滤掉。
    + f" WHERE {quote_ident('ENTRY_DT')} <= %s OR {quote_ident('ENTRY_DT')} IS NULL"
)


class PostgresStStatusRepository:
    def __init__(self, conn: psycopg.Connection[object]) -> None:
        self._conn = conn

    def st_codes_at(self, *, as_of: date, dt: date) -> frozenset[str]:
        # 不可见的日期在查库之前就失败。
        check_st_as_of(as_of=as_of, dt=dt)
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_ST_SQL, (dt.strftime(_YMD_FORMAT),))
            fetched = cur.fetchall()
        return st_codes((_st_row_from_mapping(item) for item in fetched), dt=dt)


def _st_row_from_mapping(row: dict[str, object]) -> StRow:
    code = row.get("S_INFO_WINDCODE")
    if not isinstance(code, str) or not code.strip():
        raise InvalidQueryError("ASHAREST 代码为空")
    entry = parse_ymd_optional(row.get("ENTRY_DT"), "ENTRY_DT")
    # ENTRY_DT 是可见日，不能为空。SQL 显式带回 NULL 行，在这里 fail-closed。
    if entry is None:
        raise InvalidQueryError(f"ENTRY_DT 为空: {code}")
    return StRow(
        asset_id=code,
        entry_date=entry,
        remove_date=parse_ymd_optional(row.get("REMOVE_DT"), "REMOVE_DT"),
    )
