"""从 ``JYDB`` 按 ``JSID + ID`` 取一页，并核对源端列清单。

整表镜像：不追加行过滤。每页查询走 ``(JSID, ID)`` 顺序，调用方负责在目标库
建对应索引；SQL 只用参数传值，表名与列名来自代码白名单。
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol

from quantagent.ingest.errors import SourceFetchError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from quantagent.ingest.sources.jydb.cursor import JydbCursor

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_PAGE = 10_000


class JydbPageSource(Protocol):
    def fetch_page(
        self,
        *,
        table: str,
        columns: Sequence[str],
        cursor: JydbCursor,
        limit: int,
    ) -> list[dict[str, object]]: ...

    def source_columns(self, table: str) -> list[str]: ...

    def null_jsid_count(self, table: str) -> int: ...


class PymssqlJydbPageSource:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def fetch_page(
        self,
        *,
        table: str,
        columns: Sequence[str],
        cursor: JydbCursor,
        limit: int,
    ) -> list[dict[str, object]]:
        statement = build_page_sql(table=table, columns=columns, limit=limit)
        with self._conn.cursor(as_dict=True) as cur:
            cur.execute(statement, build_page_params(cursor))
            raw_rows = cur.fetchall()
        expected = tuple(columns)
        rows: list[dict[str, object]] = []
        for index, raw in enumerate(raw_rows):
            if not isinstance(raw, dict):
                raise SourceFetchError(f"{table} 第 {index} 行不是映射")
            missing = [column for column in expected if column not in raw]
            if missing:
                raise SourceFetchError(f"{table} 第 {index} 行缺列: {missing}")
            rows.append(_normalize_bigints({column: raw.get(column) for column in expected}))
        return rows

    def source_columns(self, table: str) -> list[str]:
        _assert_ident(table, "表名")
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = %s
                ORDER BY ORDINAL_POSITION
                """,
                (table,),
            )
            return [str(row[0]) for row in cur.fetchall()]

    def null_jsid_count(self, table: str) -> int:
        _assert_ident(table, "表名")
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM [dbo].{_bracket(table)} WHERE [JSID] IS NULL")
            row = cur.fetchone()
        if row is None:
            raise SourceFetchError(f"{table} 的 JSID 空值计数没有返回")
        return int(row[0])


def build_page_sql(*, table: str, columns: Sequence[str], limit: int) -> str:
    _assert_ident(table, "表名")
    if limit < 1 or limit > _MAX_PAGE:
        raise SourceFetchError(f"page size 必须在 1..{_MAX_PAGE}: {limit}")
    if not columns:
        raise SourceFetchError("聚源分页查询列为空")
    for column in columns:
        _assert_ident(column, "列名")
    col_sql = ", ".join(_bracket(column) for column in columns)
    return (
        f"SELECT TOP ({limit}) {col_sql} FROM [dbo].{_bracket(table)} "
        f"WHERE {_bracket('JSID')} IS NOT NULL AND {_bracket('ID')} IS NOT NULL "
        f"AND ({_bracket('JSID')} > %s "
        f"OR ({_bracket('JSID')} = %s AND {_bracket('ID')} > %s)) "
        f"ORDER BY {_bracket('JSID')}, {_bracket('ID')}"
    )


def build_page_params(cursor: JydbCursor) -> tuple[object, ...]:
    return (cursor.jsid, cursor.jsid, cursor.id)


def _assert_ident(value: str, kind: str) -> None:
    if _IDENT.fullmatch(value) is None:
        raise SourceFetchError(f"聚源{kind}非法: {value}")


def _normalize_bigints(row: dict[str, object]) -> dict[str, object]:
    # pymssql 把 bigint 读成 Decimal；源列是整数，落 PG bigint 前还原成 int。
    for name in ("ID", "JSID"):
        value = row.get(name)
        if isinstance(value, Decimal) and value == value.to_integral_value():
            row[name] = int(value)
    return row


def _bracket(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"
