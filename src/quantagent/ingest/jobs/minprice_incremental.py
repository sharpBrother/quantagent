"""使用 MySQL 已完成交易日分区增量回填分钟行情。"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from quantagent.ingest.errors import SourceNotReadyError
from quantagent.ingest.jobs.minprice import ingest_day, previous_day_code_count
from quantagent.ingest.sources.minprice import list_tables
from quantagent.platform.config import assert_db_write_allowed

if TYPE_CHECKING:
    from datetime import date

    from quantagent.domain.ports.calendar import CalendarRepository
    from quantagent.domain.ports.prices import DailyPriceRepository
    from quantagent.platform.config import Settings
    from quantagent.platform.storage.paths import VarPaths


def ingest_mysql_incremental(
    mysql: Any,
    pg: Any,
    *,
    as_of: date,
    settings: Settings,
    paths: VarPaths,
    calendar: CalendarRepository,
    daily_prices: DailyPriceRepository,
    write_db: bool = False,
) -> str:
    """从最近已登记交易日向前补齐，源端未出齐或异常时停止。"""
    if write_db:
        assert_db_write_allowed(settings=settings, write_db=True)
    with pg.cursor() as cur:
        cur.execute(
            "SELECT MAX(trade_date) FROM src_minprice.lake_partition "
            "WHERE dataset=%s AND trade_date<=%s",
            ("ashare_minute_bar", as_of),
        )
        latest = cur.fetchone()[0]
    pg.rollback()
    if latest is None:
        raise SourceNotReadyError("无分钟历史分区，不能确定增量起点")
    if latest == as_of:
        return "up_to_date"
    days = calendar.list_days(
        as_of=as_of, exchange="SSE", start=latest + timedelta(days=1), end=as_of
    )
    trade_days = tuple(item for item in days if item.is_open)
    if not trade_days:
        return "up_to_date"
    if not write_db and len(trade_days) > 1:
        raise SourceNotReadyError("试运行仅支持一个待补交易日，请逐日验证")
    tables = set(list_tables(mysql, database=settings.minprice_mysql_database))
    for item in trade_days:
        day = item.cal_dt
        if item.prev_trade_dt is None:
            raise SourceNotReadyError(f"{day} 上一交易日不可用")
        if "m" + day.strftime("%Y%m%d") not in tables:
            raise SourceNotReadyError(f"{day} MySQL 分钟源表尚未就绪")
        previous_count = previous_day_code_count(pg, day=item.prev_trade_dt)
        pg.rollback()
        ingest_day(
            mysql,
            pg,
            trade_date=day,
            settings=settings,
            paths=paths,
            calendar=calendar,
            daily_prices=daily_prices,
            previous_code_count=previous_count,
            write_db=write_db,
        )
        mysql.rollback()
        pg.rollback()
    return "inserted" if write_db else "dry_run"
