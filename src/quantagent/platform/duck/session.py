"""DuckDB 会话：只连 ``:memory:``，把 Parquet 挂成视图。

不持久化 ``.duckdb`` 是存储选型的推论，不是省事：一旦落盘就会变成第二份
事实源，需要自己的备份与迁移。Parquet 才是派生数据的唯一事实源。
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import TYPE_CHECKING

import duckdb

from quantagent.platform.errors import DuckSessionError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_VIEW_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MEMORY_LIMIT = re.compile(r"^[0-9]+(?:\.[0-9]+)?[KMGT]i?B$")


def assert_ident(name: str) -> str:
    """校验可作为 DuckDB 视图名的标识符。拒绝任意字符串拼进 SQL。"""
    if not _VIEW_NAME.match(name):
        raise DuckSessionError(f"非法 DuckDB 标识符: {name!r}")
    return name


def open_session(
    *,
    memory_limit: str | None = None,
    threads: int | None = None,
) -> duckdb.DuckDBPyConnection:
    """打开纯内存会话。禁止传入文件路径——那会悄悄写出 ``.duckdb``。"""
    conn = duckdb.connect(":memory:")
    if memory_limit is not None:
        if not _MEMORY_LIMIT.match(memory_limit):
            conn.close()
            raise DuckSessionError(f"非法 memory_limit: {memory_limit!r}")
        conn.execute("SET memory_limit = ?", [memory_limit])
    if threads is not None:
        if threads < 1:
            conn.close()
            raise DuckSessionError(f"threads 必须 >= 1，收到 {threads}")
        conn.execute("SET threads = ?", [threads])
    return conn


@contextmanager
def duck_session(
    *,
    memory_limit: str | None = None,
    threads: int | None = None,
) -> Iterator[duckdb.DuckDBPyConnection]:
    conn = open_session(memory_limit=memory_limit, threads=threads)
    try:
        yield conn
    finally:
        conn.close()


def register_parquet(
    conn: duckdb.DuckDBPyConnection,
    view_name: str,
    source: Path,
    *,
    hive_partitioning: bool = True,
) -> None:
    """把一个 parquet 文件或目录挂成视图。目录为空则 fail-closed。"""
    ident = assert_ident(view_name)
    resolved = source.resolve()
    if resolved.is_file():
        if resolved.suffix != ".parquet":
            raise DuckSessionError(f"不是 parquet 文件: {resolved}")
        target = resolved.as_posix()
    elif resolved.is_dir():
        files = sorted(path for path in resolved.rglob("*.parquet") if path.is_file())
        if not files:
            raise DuckSessionError(f"没有 parquet 可挂载: {resolved}")
        # 把目录交给 DuckDB，才能解析 hive 分区目录名。
        target = resolved.as_posix()
    else:
        raise DuckSessionError(f"parquet 源不存在: {resolved}")
    relation = conn.read_parquet(
        target,
        hive_partitioning=hive_partitioning,
        union_by_name=True,
    )
    relation.create_view(ident, replace=True)
