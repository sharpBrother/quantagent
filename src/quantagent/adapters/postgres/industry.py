"""中信一级行业归属的 PostgreSQL 读取。``stock → 行业指数代码`` 反向映射，barra 用。

数据源 ``AINDEXMEMBERSCITICSZL``（中信一级 canonical 来源，2026-11-22 负责人裁定，
见 ``adapters/postgres/universe.py`` 注释）。可见性复用 ``mart.universe_member`` 契约
（成分 grade B，``knowledge_dt = INDATE`` 近似）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from psycopg.rows import dict_row

from quantagent.adapters.postgres.sql_types import quote_ident
from quantagent.adapters.postgres.src_dml import assert_src_dml_sql
from quantagent.adapters.postgres.universe import (
    load_universe_member_visibility,
    parse_ymd_optional,
)
from quantagent.domain.errors import InvalidQueryError
from quantagent.domain.pit import is_cutoff_visible, pit_cutoff
from quantagent.domain.universe.interval import interval_contains

if TYPE_CHECKING:
    from datetime import date

    import psycopg

    from quantagent.contracts.spec import VisibilityContract

_CITICS1_TABLE = "AINDEXMEMBERSCITICSZL"


class PostgresIndustryMapRepository:
    """``industry_map_at`` 的 PostgreSQL 实现。一次性读 ZL 全表，逐股切片成映射。"""

    def __init__(
        self,
        conn: psycopg.Connection[object],
        *,
        contract: VisibilityContract | None = None,
    ) -> None:
        self._conn = conn
        self._contract = (
            contract if contract is not None else load_universe_member_visibility()
        )

    def industry_map_at(self, *, as_of: date, dt: date) -> dict[str, str]:
        if dt > as_of:
            raise InvalidQueryError(f"dt {dt.isoformat()} 晚于 as_of {as_of.isoformat()}")
        cutoff = pit_cutoff(self._contract, as_of=as_of)
        columns = ("S_INFO_WINDCODE", "S_CON_WINDCODE", "S_CON_INDATE", "S_CON_OUTDATE")
        statement = assert_src_dml_sql(
            "SELECT " + ", ".join(quote_ident(name) for name in columns)
            + f" FROM {quote_ident('src_wind')}.{quote_ident(_CITICS1_TABLE)}"
        )
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(statement)
            fetched = cur.fetchall()
        # 逐行切片：INDATE 非空、可见（in_date<=cutoff）、dt 在 [INDATE, OUTDATE] 闭区间内。
        # 一股命中多个一级行业（重叠）即报错——一级行业应互斥，重叠是数据异常，不挑选。
        mapping: dict[str, str] = {}
        for row in fetched:
            index_code = row.get("S_INFO_WINDCODE")
            stock = row.get("S_CON_WINDCODE")
            if not isinstance(index_code, str) or not isinstance(stock, str):
                raise InvalidQueryError("AINDEXMEMBERSCITICSZL 行业或成分代码为空")
            in_date = parse_ymd_optional(row.get("S_CON_INDATE"), "S_CON_INDATE")
            if in_date is None:
                raise InvalidQueryError(f"S_CON_INDATE 为空: {index_code} {stock}")
            out_date = parse_ymd_optional(row.get("S_CON_OUTDATE"), "S_CON_OUTDATE")
            if not is_cutoff_visible(value=in_date, cutoff=cutoff):
                continue
            if not interval_contains(valid_from=in_date, valid_to=out_date, dt=dt):
                continue
            if stock in mapping and mapping[stock] != index_code:
                raise InvalidQueryError(
                    f"{stock} 在 {dt.isoformat()} 命中多个中信一级行业: {mapping[stock]} 与 {index_code}"
                )
            mapping[stock] = index_code
        return mapping
