"""``quantagent ingest``：外部源采集。默认干跑，不写库。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import typer

from quantagent.adapters.postgres.errors import (
    ForbiddenSqlError,
    PostgresAdapterError,
    TransactionUnknownError,
)
from quantagent.ingest.errors import IngestError
from quantagent.ingest.jobs.trade_cal import ingest_tushare_trade_cal
from quantagent.ingest.sources.tushare.trade_cal import DEFAULT_EXCHANGES
from quantagent.platform.config import get_settings
from quantagent.platform.errors import ConfigError, RunLogError, WriteGateError
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

ingest_app = typer.Typer(help="外部源采集到 PG 研究数据面。默认不写库。", no_args_is_help=True)
tushare_app = typer.Typer(help="Tushare 源。", no_args_is_help=True)
ingest_app.add_typer(tushare_app, name="tushare")

_YMD_LEN = 8


@tushare_app.command("trade-cal")
def ingest_trade_cal(
    start: Annotated[
        str, typer.Option("--start", help="起始日 YYYYMMDD 或 YYYY-MM-DD")
    ] = "19900101",
    end: Annotated[
        str | None,
        typer.Option("--end", help="结束日 YYYYMMDD 或 YYYY-MM-DD；默认今天 UTC"),
    ] = None,
    exchange: Annotated[
        list[str] | None,
        typer.Option("--exchange", help="交易所代码，可重复。默认 SSE 与 SZSE"),
    ] = None,
    write_db: Annotated[bool, typer.Option("--write-db", help="显式允许写库")] = False,
) -> None:
    """拉取 Tushare trade_cal 写入 src_tushare.trade_cal。"""
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    start_date = _compact_ymd(start, flag="--start")
    end_date = _compact_ymd(end or datetime.now(UTC).strftime("%Y%m%d"), flag="--end")
    exchanges = tuple(exchange) if exchange else DEFAULT_EXCHANGES
    try:
        result = ingest_tushare_trade_cal(
            settings=settings,
            paths=paths,
            write_db=write_db,
            start_date=start_date,
            end_date=end_date,
            exchanges=exchanges,
        )
    except (
        IngestError,
        WriteGateError,
        ConfigError,
        RunLogError,
        ForbiddenSqlError,
        TransactionUnknownError,
        PostgresAdapterError,
    ) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    mode = "wrote" if result.written else "dry-run"
    typer.echo(
        f"{mode} dataset={result.dataset} rows={result.row_count} "
        f"dml={result.dml_count} digest={result.payload_digest}"
    )


def _compact_ymd(raw: str, *, flag: str) -> str:
    compact = raw.strip().replace("-", "")
    if len(compact) != _YMD_LEN or not compact.isdigit():
        raise typer.BadParameter(f"{flag} 必须是 YYYYMMDD 或 YYYY-MM-DD", param_hint=flag)
    try:
        datetime.strptime(compact, "%Y%m%d")
    except ValueError as exc:
        raise typer.BadParameter(f"{flag} 不是合法日期: {raw}", param_hint=flag) from exc
    return compact
