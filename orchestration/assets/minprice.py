"""东财当日分钟行情资产；未出齐时等下一次补跑。"""

from datetime import date

from dagster import Config, MaterializeResult, asset


class MinuteDayConfig(Config):
    as_of: str
    write_db: bool = False
    final_attempt: bool = False


@asset(name="src_eastmoney_minute", group_name="minprice")
def src_eastmoney_minute(config: MinuteDayConfig) -> MaterializeResult[None]:
    from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
    from quantagent.adapters.postgres.universe import PostgresUniverseRepository
    from quantagent.ingest.errors import SourceNotReadyError
    from quantagent.ingest.jobs.eastmoney_minute import ingest_eastmoney_day
    from quantagent.platform.config import get_settings
    from quantagent.platform.pg import connect
    from quantagent.platform.storage import detect_repo_root, resolve_var_paths

    day = date.fromisoformat(config.as_of)
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    calendar = LakeCalendarRepository(paths.lake / "std" / "trade_calendar")
    pg = connect(settings, "src")
    try:
        try:
            result = ingest_eastmoney_day(
                pg,
                trade_date=day,
                settings=settings,
                paths=paths,
                calendar=calendar,
                universe=PostgresUniverseRepository(pg),
                write_db=config.write_db,
            )
        except SourceNotReadyError:
            if config.final_attempt:
                raise
            return MaterializeResult(metadata={"trade_date": str(day), "status": "not_ready"})
        return MaterializeResult(metadata={"trade_date": str(day), "status": result})
    finally:
        pg.close()


@asset(name="src_mysql_minute", group_name="minprice")
def src_mysql_minute(config: MinuteDayConfig) -> MaterializeResult[None]:
    """MySQL 日表未出齐时等待下一轮；校验失败不得写入部分日分区。"""
    from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
    from quantagent.adapters.postgres.daily_prices import PostgresDailyPriceRepository
    from quantagent.ingest.errors import SourceNotReadyError
    from quantagent.ingest.jobs.minprice_incremental import ingest_mysql_incremental
    from quantagent.platform.config import get_settings
    from quantagent.platform.minprice_mysql import connect_minprice
    from quantagent.platform.pg import connect
    from quantagent.platform.storage import detect_repo_root, resolve_var_paths

    day = date.fromisoformat(config.as_of)
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    calendar = LakeCalendarRepository(paths.lake / "std" / "trade_calendar")
    mysql = connect_minprice(settings)
    try:
        pg = connect(settings, "src")
        try:
            try:
                result = ingest_mysql_incremental(
                    mysql,
                    pg,
                    as_of=day,
                    settings=settings,
                    paths=paths,
                    calendar=calendar,
                    daily_prices=PostgresDailyPriceRepository(pg),
                    write_db=config.write_db,
                )
            except SourceNotReadyError:
                if config.final_attempt:
                    raise
                return MaterializeResult(metadata={"trade_date": str(day), "status": "not_ready"})
            return MaterializeResult(metadata={"trade_date": str(day), "status": result})
        finally:
            pg.close()
    finally:
        mysql.close()
