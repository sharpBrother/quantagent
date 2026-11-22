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
                write_db=config.write_db,
            )
        except SourceNotReadyError:
            if config.final_attempt:
                raise
            return MaterializeResult(metadata={"trade_date": str(day), "status": "not_ready"})
        return MaterializeResult(metadata={"trade_date": str(day), "status": result})
    finally:
        pg.close()
