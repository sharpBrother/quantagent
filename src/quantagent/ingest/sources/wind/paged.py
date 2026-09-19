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
    ) -> list[dict[str, object]]:
        statement = build_page_sql(table=table, columns=columns, limit=limit)
        with self._conn.cursor(as_dict=True) as cur:
            cur.execute(statement, (cursor.opdate, cursor.opdate, cursor.object_id))
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


def build_page_sql(*, table: str, columns: Sequence[str], limit: int) -> str:
    if not _IDENT.match(table):
        raise SourceFetchError(f"Wind 表名非法: {table}")
    if limit < 1 or limit > _MAX_PAGE:
        raise SourceFetchError(f"page size 必须在 1..{_MAX_PAGE}: {limit}")
    if not columns:
        raise SourceFetchError("Wind 分页查询列为空")
    for column in columns:
        if not _IDENT.match(column):
            raise SourceFetchError(f"Wind 列名非法: {column}")
    col_sql = ", ".join(_bracket(column) for column in columns)
    return (
        f"SELECT TOP ({limit}) {col_sql} FROM [dbo].{_bracket(table)} "
        f"WHERE {_bracket('OPDATE')} IS NOT NULL AND {_bracket('OBJECT_ID')} IS NOT NULL "
        f"AND ({_bracket('OPDATE')} > %s "
        f"OR ({_bracket('OPDATE')} = %s AND {_bracket('OBJECT_ID')} > %s)) "
        f"ORDER BY {_bracket('OPDATE')}, {_bracket('OBJECT_ID')}"
    )


def _bracket(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"
