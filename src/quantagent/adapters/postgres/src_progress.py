"""汇总 ``src_wind._batch`` 的采集进度。只读。

每页提交时，批次行与数据行在同一事务写入，所以 ``_batch`` 就是权威进度：
页在这里，数据就在库里；页回滚，批次行也不在。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from psycopg.rows import dict_row

from quantagent.adapters.postgres.src_dml import assert_src_dml_sql

if TYPE_CHECKING:
    from datetime import datetime

    import psycopg


@dataclass(frozen=True)
class TableProgress:
    dataset: str
    pages: int
    rows: int
    source_cursor: str | None
    last_commit: datetime
    recent_pages: int
    # 最近窗口内相邻两页提交时间之差的平均值；窗口内不足两页为 None。
    recent_seconds_per_page: float | None


_SQL = assert_src_dml_sql(
    """
SELECT b.dataset,
       count(*) AS pages,
       coalesce(sum(b.row_count), 0) AS rows,
       max(b.finished_at) AS last_commit,
       (SELECT l.source_cursor FROM src_wind._batch AS l
         WHERE l.dataset = b.dataset AND l.status = 'success'
         ORDER BY l._batch_id DESC LIMIT 1) AS source_cursor,
       count(*) FILTER (WHERE b.finished_at >= now() - make_interval(mins => %(window)s))
         AS recent_pages,
       extract(epoch FROM
         max(b.finished_at) FILTER (WHERE b.finished_at >= now() - make_interval(mins => %(window)s))
         - min(b.finished_at) FILTER (WHERE b.finished_at >= now() - make_interval(mins => %(window)s))
       ) AS recent_span
FROM src_wind._batch AS b
WHERE b.status = 'success'
GROUP BY b.dataset
ORDER BY max(b.finished_at) DESC
"""
)


def wind_progress(conn: psycopg.Connection[Any], *, window_minutes: int) -> list[TableProgress]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_SQL, {"window": window_minutes})
        fetched = cur.fetchall()
    out: list[TableProgress] = []
    for row in fetched:
        recent = int(row["recent_pages"])
        span = row["recent_span"]
        per_page = float(span) / (recent - 1) if recent > 1 and span is not None else None
        out.append(
            TableProgress(
                dataset=str(row["dataset"]),
                pages=int(row["pages"]),
                rows=int(row["rows"]),
                source_cursor=row["source_cursor"],
                last_commit=row["last_commit"],
                recent_pages=recent,
                recent_seconds_per_page=per_page,
            )
        )
    return out
