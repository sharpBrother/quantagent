"""东财日行情：全部股票获取成功并通过完整性检查后才登记日分区。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pyarrow.parquet as pq

from quantagent.ingest.errors import SourceFetchError
from quantagent.ingest.jobs.minprice import ingest_day
from quantagent.ingest.sources.eastmoney_minute import fetch_day, list_stocks
from quantagent.platform.config import assert_db_write_allowed
from quantagent.platform.identity import digest_file

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import date

    from quantagent.domain.ports.calendar import CalendarRepository
    from quantagent.platform.config import Settings
    from quantagent.platform.storage.paths import VarPaths

_BATCH_ROWS = 200_000


def _batches(codes: tuple[str, ...], day: date) -> Iterator[list[Any]]:
    rows: list[Any] = []
    for code in codes:
        rows.extend(fetch_day(code, trade_date=day))
        if len(rows) >= _BATCH_ROWS:
            yield rows
            rows = []
    if rows:
        yield rows


def ingest_eastmoney_day(
    pg: Any,
    *,
    trade_date: date,
    settings: Settings,
    paths: VarPaths,
    calendar: CalendarRepository,
    write_db: bool = False,
) -> str:
    """以东财股票列表采集当日，任何请求失败都不登记部分日行情。"""
    if write_db:
        assert_db_write_allowed(settings=settings, write_db=True)
        with pg.cursor() as cur:
            cur.execute(
                "SELECT file_name,row_count,file_sha256 FROM src_minprice.lake_partition "
                "WHERE dataset=%s AND trade_date=%s",
                ("ashare_minute_bar", trade_date),
            )
            existing = cur.fetchone()
        if existing is not None:
            root = (paths.lake / "src" / "minprice" / "ashare_minute_bar").resolve()
            path = (root / existing[0]).resolve()
            if (
                not path.is_relative_to(root)
                or not path.is_file()
                or pq.ParquetFile(path).metadata.num_rows != existing[1]
                or digest_file(path) != existing[2]
            ):
                raise SourceFetchError("已登记的分钟分区缺失或损坏")
            return "skipped"
    days = calendar.list_days(as_of=trade_date, exchange="SSE", start=trade_date, end=trade_date)
    if len(days) != 1 or not days[0].is_open or days[0].prev_trade_dt is None:
        raise SourceFetchError("当日或上一交易日日历不可用")
    with pg.cursor() as cur:
        cur.execute(
            "SELECT code_count FROM src_minprice.lake_partition WHERE dataset=%s AND trade_date=%s",
            ("ashare_minute_bar", days[0].prev_trade_dt),
        )
        previous = cur.fetchone()
    if previous is None or previous[0] <= 0:
        raise SourceFetchError("上一交易日分钟分区缺失，不能判断当日完整性")
    # 全市场请求可能持续较久；读取上一日清单后释放 PG 只读事务。
    pg.rollback()
    codes = list_stocks()
    if not codes:
        raise SourceFetchError("东财股票列表为空")
    return ingest_day(
        None,
        pg,
        trade_date=trade_date,
        settings=settings,
        paths=paths,
        calendar=calendar,
        previous_code_count=int(previous[0]),
        source_batches=_batches(codes, trade_date),
        source_table="eastmoney.trends2",
        write_db=write_db,
    )
