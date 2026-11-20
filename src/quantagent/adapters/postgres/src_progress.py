"""汇总各源 schema 的 ``_batch`` 采集进度。只读。

每页提交时，批次行与数据行在同一事务写入，所以 ``_batch`` 就是权威进度：
页在这里，数据就在库里；页回滚，批次行也不在。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from psycopg.rows import dict_row

from quantagent.adapters.postgres.sql_types import quote_ident
from quantagent.adapters.postgres.src_dml import assert_src_dml_sql

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    import psycopg


# 所有源 schema。schema 名只能来自这里，不得拼接外部输入；查询时经 quote_ident 引用。
SRC_SCHEMAS = ("src_wind", "src_tushare", "src_macro", "src_jydb", "src_suntime")


@dataclass(frozen=True)
class TableProgress:
    schema: str
    dataset: str
    pages: int
    rows: int
    source_cursor: str | None
    last_commit: datetime
    recent_pages: int
    # 最近窗口内相邻两页提交时间之差的平均值；窗口内不足两页为 None。
    recent_seconds_per_page: float | None


# ``{batch}`` 只能由 ``_progress_sql`` 填入经 quote_ident 引用的 ``<schema>._batch``。
_PROGRESS_TEMPLATE = """
SELECT b.dataset,
       count(*) AS pages,
       coalesce(sum(b.row_count), 0) AS rows,
       max(b.finished_at) AS last_commit,
       (SELECT l.source_cursor FROM {batch} AS l
         WHERE l.dataset = b.dataset AND l.status = 'success'
         ORDER BY l._batch_id DESC LIMIT 1) AS source_cursor,
       count(*) FILTER (WHERE b.finished_at >= now() - make_interval(mins => %(window)s))
         AS recent_pages,
       extract(epoch FROM
         max(b.finished_at) FILTER (WHERE b.finished_at >= now() - make_interval(mins => %(window)s))
         - min(b.finished_at) FILTER (WHERE b.finished_at >= now() - make_interval(mins => %(window)s))
       ) AS recent_span
FROM {batch} AS b
WHERE b.status = 'success'
GROUP BY b.dataset
ORDER BY max(b.finished_at) DESC
"""


def _progress_sql(schema: str) -> str:
    batch = f"{quote_ident(schema)}.{quote_ident('_batch')}"
    return assert_src_dml_sql(_PROGRESS_TEMPLATE.format(batch=batch))


def latest_written_value(
    conn: psycopg.Connection[Any],
    *,
    pg_schema: str,
    table: str,
    column: str,
) -> str | None:
    """按 ``_batch_id`` 倒序取表里最近写入的一行的 ``column``；表为空返回 None。只读。
    GPR 用它取最近一次写入的 ``file_sha256``。同一次运行写入的所有行共享这个值，
    所以取到的就是最近一次真正写过库的文件。不用批次表，因为写入器在没有任何值变化时
    也会登记批次行，那行并不代表文件内容变过。
    """
    statement = assert_src_dml_sql(
        f"SELECT {quote_ident(column)} FROM {quote_ident(pg_schema)}.{quote_ident(table)} "
        f"ORDER BY {quote_ident('_batch_id')} DESC LIMIT 1"
    )
    with conn.cursor() as cur:
        cur.execute(statement)
        fetched = cur.fetchone()
    if fetched is None or fetched[0] is None:
        return None
    return str(fetched[0])


def latest_version_values(
    conn: psycopg.Connection[Any],
    *,
    pg_schema: str,
    table: str,
    key_columns: Sequence[str],
    version_column: str,
    value_column: str,
) -> dict[tuple[Any, ...], tuple[Any, Any]]:
    """每个键取版本列最大的那一行，返回 ``键 -> (版本, 值)``；表为空返回空字典。只读。
    GPR 用它取每个 ``(series_id, observation_date)`` 当前的 ``file_vintage`` 与 ``value``，
    据此判断新文件里的值是否真的变了。与写入同一连接时，读到的是同一事务内的快照。
    """
    keys_sql = ", ".join(quote_ident(name) for name in key_columns)
    statement = assert_src_dml_sql(
        f"SELECT DISTINCT ON ({keys_sql}) {keys_sql}, "
        f"{quote_ident(version_column)}, {quote_ident(value_column)} "
        f"FROM {quote_ident(pg_schema)}.{quote_ident(table)} "
        f"ORDER BY {keys_sql}, {quote_ident(version_column)} DESC"
    )
    width = len(key_columns)
    found: dict[tuple[Any, ...], tuple[Any, Any]] = {}
    with conn.cursor() as cur:
        cur.execute(statement)
        for row in cur.fetchall():
            found[tuple(row[:width])] = (row[width], row[width + 1])
    return found


def values_at_version(
    conn: psycopg.Connection[Any],
    *,
    pg_schema: str,
    table: str,
    key_columns: Sequence[str],
    version_column: str,
    version: object,
    value_columns: Sequence[str],
) -> dict[tuple[Any, ...], tuple[Any, ...]]:
    """版本列等于 ``version`` 的行：返回 ``键 -> 指定值列``。只读。
    用于判断某个 file_vintage 下已有的同键行是否与本次内容一致。
    """
    keys_sql = ", ".join(quote_ident(name) for name in key_columns)
    values_sql = ", ".join(quote_ident(name) for name in value_columns)
    statement = assert_src_dml_sql(
        f"SELECT {keys_sql}, {values_sql} FROM {quote_ident(pg_schema)}.{quote_ident(table)} "
        f"WHERE {quote_ident(version_column)} = %s"
    )
    width = len(key_columns)
    with conn.cursor() as cur:
        cur.execute(statement, (version,))
        return {tuple(row[:width]): tuple(row[width:]) for row in cur.fetchall()}


def latest_success_window_end(
    conn: psycopg.Connection[Any],
    *,
    pg_schema: str,
    dataset: str,
) -> str | None:
    """最近一次成功提交的批次的 ``window_end``；没有成功批次返回 None。只读。

    日更起点由它推出。批次与数据同事务提交，所以这里看到的一定是已入库的区间。
    """
    statement = assert_src_dml_sql(
        f"SELECT window_end FROM {quote_ident(pg_schema)}.{quote_ident('_batch')} "
        "WHERE dataset = %s AND status = 'success' "
        f"ORDER BY {quote_ident('_batch_id')} DESC LIMIT 1"
    )
    with conn.cursor() as cur:
        cur.execute(statement, (dataset,))
        fetched = cur.fetchone()
    if fetched is None or fetched[0] is None:
        return None
    return str(fetched[0])


def src_progress(
    conn: psycopg.Connection[Any],
    *,
    schemas: Sequence[str],
    window_minutes: int,
) -> list[TableProgress]:
    """汇总给定源 schema 的 ``_batch`` 进度，合并后按最后提交时间倒序。只读。
    schema 必须在 ``SRC_SCHEMAS`` 内，否则抛 ``ValueError``，不发出任何查询。
    没有成功批次的 schema 不产生行。
    """
    unknown = [name for name in schemas if name not in SRC_SCHEMAS]
    if unknown:
        raise ValueError(f"未知源 schema: {unknown}；允许: {list(SRC_SCHEMAS)}")
    out: list[TableProgress] = []
    for schema in schemas:
        statement = _progress_sql(schema)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(statement, {"window": window_minutes})
            fetched = cur.fetchall()
        for row in fetched:
            recent = int(row["recent_pages"])
            span = row["recent_span"]
            per_page = float(span) / (recent - 1) if recent > 1 and span is not None else None
            out.append(
                TableProgress(
                    schema=schema,
                    dataset=str(row["dataset"]),
                    pages=int(row["pages"]),
                    rows=int(row["rows"]),
                    source_cursor=row["source_cursor"],
                    last_commit=row["last_commit"],
                    recent_pages=recent,
                    recent_seconds_per_page=per_page,
                )
            )
    out.sort(key=lambda item: item.last_commit, reverse=True)
    return out


def wind_progress(conn: psycopg.Connection[Any], *, window_minutes: int) -> list[TableProgress]:
    return src_progress(conn, schemas=("src_wind",), window_minutes=window_minutes)
