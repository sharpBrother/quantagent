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
from quantagent.adapters.postgres.wind_first_batch_columns import FIRST_BATCH_WIND_SYNC
from quantagent.adapters.postgres.wind_large_columns import LARGE_WIND_SYNC
from quantagent.ingest.errors import IngestError
from quantagent.ingest.jobs.trade_cal import ingest_tushare_trade_cal
from quantagent.ingest.jobs.wind_paged import DEFAULT_PAGE_SIZE, ingest_wind_paged
from quantagent.ingest.sources.tushare.trade_cal import DEFAULT_EXCHANGES
from quantagent.platform.config import get_settings
from quantagent.platform.errors import ConfigError, RunLogError, WriteGateError
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

ingest_app = typer.Typer(help="外部源采集到 PG 研究数据面。默认不写库。", no_args_is_help=True)
tushare_app = typer.Typer(help="Tushare 源。", no_args_is_help=True)
wind_app = typer.Typer(help="Wind wind_db 源。历史回填与日更共用。", no_args_is_help=True)
ingest_app.add_typer(tushare_app, name="tushare")
ingest_app.add_typer(wind_app, name="wind")

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


@wind_app.command("ASHARECALENDAR")
@wind_app.command("ASHAREEODPRICES")
@wind_app.command("AINDEXEODPRICES")
@wind_app.command("ASHAREMONEYFLOW")
@wind_app.command("ASHAREEODDERIVATIVEINDICATOR")
@wind_app.command("ASHARECASHFLOW")
@wind_app.command("ASHAREINCOME")
@wind_app.command("ASHAREBALANCESHEET")
@wind_app.command("AINDEXVALUATION")
def ingest_wind_table(
    ctx: typer.Context,
    *,
    write_db: Annotated[bool, typer.Option("--write-db", help="显式允许写库")] = False,
    replace_existing: Annotated[
        bool,
        typer.Option(
            "--replace-existing", help="允许 DELETE+INSERT 替换已有键，以及 OPMODE=2 删除"
        ),
    ] = False,
    page_size: Annotated[
        int, typer.Option("--page-size", help="每页行数，默认 1000")
    ] = DEFAULT_PAGE_SIZE,
    max_pages: Annotated[
        int | None,
        typer.Option("--max-pages", help="最多处理页数；干跑默认 1，真写默认不限制"),
    ] = None,
    from_cursor: Annotated[
        str | None,
        typer.Option("--from-cursor", help="覆盖起点游标 JSON：{opdate,object_id}"),
    ] = None,
) -> None:
    """从 wind_db 按 OPDATE+OBJECT_ID 分页写入同名 Wind 源镜像。"""
    table = ctx.info_name
    assert table is not None
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    try:
        result = ingest_wind_paged(
            settings=settings,
            paths=paths,
            table=table,
            write_db=write_db,
            replace_existing=replace_existing,
            page_size=page_size,
            max_pages=max_pages,
            from_cursor=from_cursor,
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
    if result.written:
        mode = "wrote"
    elif write_db:
        mode = "caught-up"
    else:
        mode = "dry-run"
    typer.echo(
        f"{mode} dataset={result.dataset} table={result.table} pages={result.pages} "
        f"rows={result.row_count} inserted={result.inserted} replaced={result.replaced} "
        f"deleted={result.deleted} skipped={result.skipped} "
        f"metadata_skipped={result.metadata_skipped} auto_replaced={result.auto_replaced} "
        f"dml={result.dml_count} "
        f"digest={result.payload_digest} cursor={result.source_cursor}"
    )


for _name in FIRST_BATCH_WIND_SYNC:
    wind_app.command(_name)(ingest_wind_table)


_ReplaceOption = Annotated[
    str | None,
    typer.Option(
        "--replace-existing",
        metavar="TABLE",
        help="只对这一张表允许 DELETE+INSERT 替换已有键与 OPMODE=2 删除；其余表仍拒绝覆盖",
    ),
]
_MaxPagesOption = Annotated[
    int | None,
    typer.Option("--max-pages", help="每张表最多处理页数；干跑默认 1，真写默认不限制"),
]
_FromCursorOption = Annotated[
    str | None,
    typer.Option("--from-cursor", help="只用于单表。按顺序跑多张表时不要传"),
]


@wind_app.command("large")
def ingest_wind_large(
    *,
    write_db: Annotated[bool, typer.Option("--write-db", help="显式允许写库")] = False,
    replace_existing: _ReplaceOption = None,
    page_size: Annotated[
        int,
        typer.Option(
            "--page-size",
            help="每页行数。这批大表默认 10000，是分页上限，也是指数全量测到的较快档",
        ),
    ] = 10_000,
    max_pages: _MaxPagesOption = None,
    from_cursor: _FromCursorOption = None,
) -> None:
    """按源库体积从大到小同步达到 3GB 的表。默认每张干跑。"""
    _run_wind_sequence(
        LARGE_WIND_SYNC,
        write_db=write_db,
        replace_existing=replace_existing,
        page_size=page_size,
        max_pages=max_pages,
        from_cursor=from_cursor,
    )


@wind_app.command("first-batch")
def ingest_wind_first_batch(
    *,
    write_db: Annotated[bool, typer.Option("--write-db", help="显式允许写库")] = False,
    replace_existing: _ReplaceOption = None,
    page_size: Annotated[
        int, typer.Option("--page-size", help="每页行数，默认 10000（分页上限）")
    ] = 10_000,
    max_pages: _MaxPagesOption = None,
    from_cursor: _FromCursorOption = None,
) -> None:
    """同步第一批其余常规 Wind 表：股票池与成分表在前。默认每张干跑。"""
    _run_wind_sequence(
        FIRST_BATCH_WIND_SYNC,
        write_db=write_db,
        replace_existing=replace_existing,
        page_size=page_size,
        max_pages=max_pages,
        from_cursor=from_cursor,
    )


def _run_wind_sequence(
    tables: tuple[str, ...],
    *,
    write_db: bool,
    replace_existing: str | None,
    page_size: int,
    max_pages: int | None,
    from_cursor: str | None,
) -> None:
    if from_cursor is not None:
        typer.secho("按顺序同步多张表时不能传 --from-cursor", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    # 替换必须指定范围（AGENTS.md §6.4）：一次只放开一张表，避免一个开关覆盖整批表。
    if replace_existing is not None and replace_existing not in tables:
        typer.secho(
            f"--replace-existing 必须是 {', '.join(tables)} 之一: {replace_existing}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    for table in tables:
        try:
            result = ingest_wind_paged(
                settings=settings,
                paths=paths,
                table=table,
                write_db=write_db,
                replace_existing=table == replace_existing,
                page_size=page_size,
                max_pages=max_pages,
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
            typer.secho(f"{table} {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from exc
        if result.written:
            mode = "wrote"
        elif write_db:
            mode = "caught-up"
        else:
            mode = "dry-run"
        typer.echo(
            f"{mode} dataset={result.dataset} table={result.table} pages={result.pages} "
            f"rows={result.row_count} metadata_skipped={result.metadata_skipped} "
            f"auto_replaced={result.auto_replaced} "
            f"dml={result.dml_count} cursor={result.source_cursor}"
        )
