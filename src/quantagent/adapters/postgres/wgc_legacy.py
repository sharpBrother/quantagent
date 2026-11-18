"""WGC 旧库报告期与发布日期映射的只读查询。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from quantagent.adapters.postgres.errors import PostgresAdapterError

if TYPE_CHECKING:
    import psycopg


def wgc_report_dates(conn: psycopg.Connection[Any]) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT period_end, publish_date FROM src_macro.macro_wgc_gold_demand "
            "WHERE geography = %s AND category = %s AND source = %s",
            ("WORLD", "BARS", "wgc:gdt_report_page"),
        )
        dates: dict[str, str] = {}
        for period, date in cur.fetchall():
            if period in dates and dates[period] != date:
                raise PostgresAdapterError(f"WGC 旧报告发布日期不唯一: {period}")
            dates[str(period)] = str(date)
        return dates
