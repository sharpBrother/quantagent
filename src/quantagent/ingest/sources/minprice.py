"""读取 MySQL 分日行情；表名同时通过格式和源端清单校验。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from quantagent.ingest.errors import SourceFetchError

if TYPE_CHECKING:
    from collections.abc import Iterator

_TABLE = re.compile(r"m[0-9]{8}\Z")
_COLUMNS = "ts_code, trade_time, `open`, high, low, `close`, vol, amount"


def list_tables(conn: Any, *, database: str) -> tuple[str, ...]:
    """只返回符合命名约定的源表，其他表不能拼入查询。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
            (database,),
        )
        return tuple(sorted(str(row[0]) for row in cur if _TABLE.fullmatch(str(row[0]))))


def read_day(
    conn: Any, *, database: str, table: str, batch_size: int = 200_000
) -> Iterator[list[Any]]:
    """流式读取一日原始行，调用方必须消费或关闭迭代器。"""
    if not _TABLE.fullmatch(table) or table not in list_tables(conn, database=database):
        raise SourceFetchError(f"分钟行情源表不在清单中: {table!r}")
    if batch_size <= 0:
        raise ValueError("batch_size 必须为正")
    # 数据库由连接选择，表名经过正则及 information_schema 双重校验。
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM `{table}`")
        while rows := cur.fetchmany(batch_size):
            yield list(rows)
