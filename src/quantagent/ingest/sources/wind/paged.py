"""从 ``wind_db`` 按 ``OPDATE + OBJECT_ID`` 取一页。表名必须来自白名单。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Protocol

from quantagent.ingest.errors import SourceFetchError
from quantagent.ingest.sources.wind.decode import decode_chi_row

if TYPE_CHECKING:
    from collections.abc import Sequence

    from quantagent.ingest.sources.wind.cursor import WindCursor

_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_MAX_PAGE = 10_000


class WindPageSource(Protocol):
    def fetch_page(
        self,
        *,
        table: str,
        columns: Sequence[str],
        cursor: WindCursor,
        limit: int,
        chi_fields: tuple[str, ...] = (),
        source_filter: tuple[tuple[str, tuple[object, ...]], ...] = (),
    ) -> list[dict[str, object]]: ...


class PymssqlWindPageSource:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def fetch_page(
        self,
        *,
        table: str,
        columns: Sequence[str],
        cursor: WindCursor,
        limit: int,
        chi_fields: tuple[str, ...] = (),
        source_filter: tuple[tuple[str, tuple[object, ...]], ...] = (),
    ) -> list[dict[str, object]]:
        statement = build_page_sql(
            table=table, columns=columns, limit=limit, source_filter=source_filter
        )
        with self._conn.cursor(as_dict=True) as cur:
            cur.execute(statement, build_page_params(cursor, source_filter))
            raw_rows = cur.fetchall()
        rows: list[dict[str, object]] = []
        expected = tuple(columns)
        for index, raw in enumerate(raw_rows):
            if not isinstance(raw, dict):
                raise SourceFetchError(f"{table} 第 {index} 行不是映射")
            payload = {column: raw.get(column) for column in expected}
            missing = [column for column, value in payload.items() if column not in raw]
            if missing:
                raise SourceFetchError(f"{table} 第 {index} 行缺列: {missing}")
            rows.append(decode_chi_row(payload, chi_fields))
        return rows

    def source_columns(self, table: str) -> list[str]:
        if not _IDENT.match(table):
            raise SourceFetchError(f"Wind 表名非法: {table}")
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


def build_page_sql(
    *,
    table: str,
    columns: Sequence[str],
    limit: int,
    source_filter: tuple[tuple[str, tuple[object, ...]], ...] = (),
) -> str:
    """游标条件之外再追加源端过滤。过滤值只走参数，列名必须通过标识符校验。

    没有过滤时输出与引入过滤前逐字相同，全表镜像的表不受影响。
    """
    if not _IDENT.match(table):
        raise SourceFetchError(f"Wind 表名非法: {table}")
    if limit < 1 or limit > _MAX_PAGE:
        raise SourceFetchError(f"page size 必须在 1..{_MAX_PAGE}: {limit}")
    if not columns:
        raise SourceFetchError("Wind 分页查询列为空")
    for column in columns:
        if not _IDENT.match(column):
            raise SourceFetchError(f"Wind 列名非法: {column}")
    filter_sql = ""
    for column, values in source_filter:
        if not _IDENT.match(column):
            raise SourceFetchError(f"Wind 过滤列名非法: {column}")
        if not values:
            # IN () 在 T-SQL 里是语法错误；空允许集合说明规格写错了，直接停。
            raise SourceFetchError(f"Wind 过滤列没有允许值: {column}")
        placeholders = ", ".join("%s" for _ in values)
        filter_sql += f" AND {_bracket(column)} IN ({placeholders})"
    col_sql = ", ".join(_bracket(column) for column in columns)
    return (
        f"SELECT TOP ({limit}) {col_sql} FROM [dbo].{_bracket(table)} "
        f"WHERE {_bracket('OPDATE')} IS NOT NULL AND {_bracket('OBJECT_ID')} IS NOT NULL "
        f"AND ({_bracket('OPDATE')} > %s "
        f"OR ({_bracket('OPDATE')} = %s AND {_bracket('OBJECT_ID')} > %s))"
        f"{filter_sql} "
        f"ORDER BY {_bracket('OPDATE')}, {_bracket('OBJECT_ID')}"
    )


def build_page_params(
    cursor: WindCursor,
    source_filter: tuple[tuple[str, tuple[object, ...]], ...] = (),
) -> tuple[object, ...]:
    """参数顺序必须与 build_page_sql 里占位符的出现顺序一致：先游标三个，再过滤值。"""
    params: list[object] = [cursor.opdate, cursor.opdate, cursor.object_id]
    for _, values in source_filter:
        params.extend(values)
    return tuple(params)


def _bracket(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"
