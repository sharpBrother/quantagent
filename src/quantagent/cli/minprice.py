"""分钟源历史回填及分区校验。"""

from __future__ import annotations

from datetime import date
from typing import Annotated

import pyarrow.parquet as pq
import typer

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.ingest.jobs.eastmoney_minute import ingest_eastmoney_day
from quantagent.ingest.jobs.minprice import ingest_day
from quantagent.ingest.sources.minprice import list_tables
from quantagent.platform.config import assert_db_write_allowed, get_settings
from quantagent.platform.identity import digest_file
from quantagent.platform.minprice_mysql import connect_minprice
from quantagent.platform.pg import connect
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

minprice_app = typer.Typer(help="MySQL 分钟源镜像。", no_args_is_help=True)


@minprice_app.command("backfill")
def backfill(
    start: Annotated[str, typer.Option("--start", help="开始交易日 YYYY-MM-DD")],
    end: Annotated[str, typer.Option("--end", help="结束交易日 YYYY-MM-DD")],
    write_db: Annotated[bool, typer.Option("--write-db")] = False,
) -> None:
    settings = get_settings()
    if write_db:
        assert_db_write_allowed(settings=settings, write_db=True)
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last:
        raise typer.BadParameter("start 晚于 end")
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    calendar = LakeCalendarRepository(paths.lake / "std" / "trade_calendar")
    days = calendar.list_days(as_of=last, exchange="SSE", start=first, end=last)
    trading_days = [item.cal_dt for item in days if item.is_open]
    if not trading_days:
        raise typer.BadParameter("区间内无交易日")
    mysql = connect_minprice(settings)
    try:
        names = set(list_tables(mysql, database=settings.minprice_mysql_database))
        missing = [
            day.isoformat() for day in trading_days if "m" + day.strftime("%Y%m%d") not in names
        ]
        if missing:
            raise typer.BadParameter(f"源端缺少交易日表: {', '.join(missing)}")
        pg = connect(settings, "src")
        try:
            for day in trading_days:
                status = ingest_day(
                    mysql,
                    pg,
                    trade_date=day,
                    settings=settings,
                    paths=paths,
                    calendar=calendar,
                    write_db=write_db,
                )
                typer.echo(f"{day}: {status}")
                # 长时间回填应在每个交易日后释放只读快照。
                mysql.rollback()
                pg.rollback()
        finally:
            pg.close()
    finally:
        mysql.close()


@minprice_app.command("eastmoney-day")
def eastmoney_day(
    trade_date: Annotated[str, typer.Option("--date", help="交易日 YYYY-MM-DD")],
    write_db: Annotated[bool, typer.Option("--write-db")] = False,
) -> None:
    """从东财读取当日全市场行情，默认不落盘。"""
    settings = get_settings()
    if write_db:
        assert_db_write_allowed(settings=settings, write_db=True)
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    calendar = LakeCalendarRepository(paths.lake / "std" / "trade_calendar")
    pg = connect(settings, "src")
    try:
        result = ingest_eastmoney_day(
            pg,
            trade_date=date.fromisoformat(trade_date),
            settings=settings,
            paths=paths,
            calendar=calendar,
            write_db=write_db,
        )
        typer.echo(f"{trade_date}: {result}")
    finally:
        pg.close()


@minprice_app.command("verify")
def verify() -> None:
    """校验登记文件的 SHA256 与行数，列出未登记文件。"""
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    root = (paths.lake / "src" / "minprice" / "ashare_minute_bar").resolve()
    with connect(settings, "src") as pg, pg.cursor() as cur:
        cur.execute(
            "SELECT file_name,row_count,file_sha256 FROM src_minprice.lake_partition "
            "WHERE dataset=%s ORDER BY trade_date",
            ("ashare_minute_bar",),
        )
        rows = cur.fetchall()
    referenced = set()
    errors = [] if rows else ["分钟分区清单为空，无法验证"]
    for name, count, sha in rows:
        path = (root / name).resolve()
        referenced.add(path)
        if not path.is_relative_to(root) or not path.is_file():
            errors.append(f"缺失或路径非法: {name}")
        elif pq.ParquetFile(path).metadata.num_rows != count or digest_file(path) != sha:
            errors.append(f"内容或行数不符: {name}")
    orphans = sorted(path for path in root.rglob("*.parquet") if path.resolve() not in referenced)
    for path in orphans:
        typer.echo(f"未登记: {path.relative_to(root)}")
    for error in errors:
        typer.echo(error, err=True)
    typer.echo(f"已登记={len(rows)} 未登记={len(orphans)} 错误={len(errors)}")
    if errors:
        raise typer.Exit(code=1)
