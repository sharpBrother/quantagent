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
from quantagent.adapters.postgres.src_progress import wind_progress
from quantagent.adapters.postgres.wind_first_batch_columns import FIRST_BATCH_WIND_SYNC
from quantagent.adapters.postgres.wind_large_columns import LARGE_WIND_SYNC
from quantagent.ingest.errors import IngestError
from quantagent.ingest.jobs.macro_fred import ingest_macro_fred
from quantagent.ingest.jobs.macro_gpr import ingest_macro_gpr
from quantagent.ingest.jobs.trade_cal import ingest_tushare_trade_cal
from quantagent.ingest.jobs.tushare_shibor import ingest_tushare_shibor
from quantagent.ingest.jobs.tushare_us_treasury_yield import ingest_tushare_us_treasury_yield
from quantagent.ingest.jobs.wind_paged import DEFAULT_PAGE_SIZE, ingest_wind_paged
from quantagent.ingest.jobs.wind_verify import verify_wind_table
from quantagent.ingest.sources.tushare.trade_cal import DEFAULT_EXCHANGES
from quantagent.platform.config import get_settings
from quantagent.platform.errors import ConfigError, RunLogError, WriteGateError
from quantagent.platform.pg import connect
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

ingest_app = typer.Typer(help="外部源采集到 PG 研究数据面。默认不写库。", no_args_is_help=True)
tushare_app = typer.Typer(help="Tushare 源。", no_args_is_help=True)
wind_app = typer.Typer(help="Wind wind_db 源。历史回填与日更共用。", no_args_is_help=True)
macro_app = typer.Typer(help="宏观公开数据源。", no_args_is_help=True)
ingest_app.add_typer(tushare_app, name="tushare")
ingest_app.add_typer(wind_app, name="wind")
ingest_app.add_typer(macro_app, name="macro")

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


@tushare_app.command("shibor")
def ingest_shibor(
    start: Annotated[str, typer.Option("--start", help="起始日 YYYYMMDD 或 YYYY-MM-DD；必填")],
    end: Annotated[
        str | None,
        typer.Option("--end", help="结束日 YYYYMMDD 或 YYYY-MM-DD；默认今天 UTC"),
    ] = None,
    write_db: Annotated[bool, typer.Option("--write-db", help="显式允许写库")] = False,
) -> None:
    """拉取 Tushare shibor，按自然月分段写入 src_tushare.shibor。默认干跑。"""
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    start_date = _compact_ymd(start, flag="--start")
    end_date = _compact_ymd(end or datetime.now(UTC).strftime("%Y%m%d"), flag="--end")
    try:
        result = ingest_tushare_shibor(
            settings=settings,
            paths=paths,
            write_db=write_db,
            start_date=start_date,
            end_date=end_date,
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
    empty = ",".join(result.empty_segments) or "无"
    if result.written:
        typer.echo(
            f"wrote dataset={result.dataset} segments={result.segments} rows={result.row_count} "
            f"inserted={result.inserted} replaced={result.replaced} skipped={result.skipped} "
            f"metadata_skipped={result.metadata_skipped} dml={result.dml_count} "
            f"batches={len(result.batch_ids)} empty_segments={empty} "
            f"digest={result.output_digest}"
        )
    else:
        typer.echo(
            f"dry-run dataset={result.dataset} segments={result.segments} "
            f"rows={result.row_count} empty_segments={empty} digest={result.payload_digest}"
        )


@tushare_app.command("us-treasury-yield")
def ingest_us_treasury_yield(
    start: Annotated[str, typer.Option("--start", help="起始日 YYYYMMDD 或 YYYY-MM-DD；必填")],
    end: Annotated[
        str | None,
        typer.Option("--end", help="结束日 YYYYMMDD 或 YYYY-MM-DD；默认今天 UTC"),
    ] = None,
    write_db: Annotated[bool, typer.Option("--write-db", help="显式允许写库")] = False,
) -> None:
    """拉取 Tushare us_tycr，按自然月分段写入 src_tushare.us_treasury_yield。默认干跑。"""
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    start_date = _compact_ymd(start, flag="--start")
    end_date = _compact_ymd(end or datetime.now(UTC).strftime("%Y%m%d"), flag="--end")
    try:
        result = ingest_tushare_us_treasury_yield(
            settings=settings,
            paths=paths,
            write_db=write_db,
            start_date=start_date,
            end_date=end_date,
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
    empty = ",".join(result.empty_segments) or "无"
    if result.written:
        typer.echo(
            f"wrote dataset={result.dataset} segments={result.segments} rows={result.row_count} "
            f"inserted={result.inserted} replaced={result.replaced} skipped={result.skipped} "
            f"metadata_skipped={result.metadata_skipped} dml={result.dml_count} "
            f"batches={len(result.batch_ids)} empty_segments={empty} "
            f"digest={result.output_digest}"
        )
    else:
        typer.echo(
            f"dry-run dataset={result.dataset} segments={result.segments} "
            f"rows={result.row_count} empty_segments={empty} digest={result.payload_digest}"
        )


@macro_app.command("fred")
def ingest_macro_fred_command(
    series: Annotated[
        list[str] | None,
        typer.Option("--series", help="序列号，可重复。默认 DFII10、T10YIE、CPIAUCSL 全部"),
    ] = None,
    write_db: Annotated[bool, typer.Option("--write-db", help="显式允许写库")] = False,
) -> None:
    """拉取 FRED／ALFRED 全部历史版本，写入 src_macro.fred_observation_vintage。默认干跑。"""
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    try:
        result = ingest_macro_fred(
            settings=settings,
            paths=paths,
            write_db=write_db,
            series_ids=series,
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
    for item in result.series:
        write = item.write
        if write.written:
            typer.echo(
                f"wrote dataset={result.dataset} series={item.series_id} pages={item.pages} "
                f"rows={write.row_count} inserted={write.inserted} replaced={write.replaced} "
                f"skipped={write.skipped} metadata_skipped={write.metadata_skipped} "
                f"dml={write.dml_count} batch={write.batch_id} digest={write.output_digest}"
            )
        else:
            typer.echo(
                f"dry-run dataset={result.dataset} series={item.series_id} pages={item.pages} "
                f"rows={write.row_count} digest={write.payload_digest}"
            )


@macro_app.command("gpr")
def ingest_macro_gpr_command(
    write_db: Annotated[bool, typer.Option("--write-db", help="显式允许写库")] = False,
) -> None:
    """下载 GPR 日频 dta，跟随源端写入 src_macro.gpr_daily。与库内最近一次文件相同则不写库。默认干跑。"""
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    try:
        result = ingest_macro_gpr(settings=settings, paths=paths, write_db=write_db)
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
    head = (
        f"dataset={result.dataset} file_vintage={result.file_vintage:%Y%m%d} "
        f"observed={result.observation_min:%Y%m%d}..{result.observation_max:%Y%m%d} "
        f"file_sha256={result.file_sha256}"
    )
    series = " ".join(f"{series_id}={rows}" for series_id, rows in result.series_rows)
    if result.unchanged:
        typer.echo(f"无更新 {head} 未写库")
    elif result.written:
        typer.echo(
            f"wrote {head} rows={result.row_count} inserted={result.inserted} "
            f"replaced={result.replaced} skipped={result.skipped} "
            f"metadata_skipped={result.metadata_skipped} dml={result.dml_count} "
            f"batch={result.batch_id} digest={result.output_digest}"
        )
    else:
        typer.echo(f"dry-run {head} rows={result.row_count} digest={result.payload_digest}")
    typer.echo(f"series_rows: {series}")


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
        f"metadata_skipped={result.metadata_skipped} "
        f"dml={result.dml_count} "
        f"digest={result.payload_digest} cursor={result.source_cursor}"
    )


for _name in FIRST_BATCH_WIND_SYNC:
    wind_app.command(_name)(ingest_wind_table)


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
        page_size=page_size,
        max_pages=max_pages,
        from_cursor=from_cursor,
    )


@wind_app.command("first-batch")
def ingest_wind_first_batch(
    *,
    write_db: Annotated[bool, typer.Option("--write-db", help="显式允许写库")] = False,
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
        page_size=page_size,
        max_pages=max_pages,
        from_cursor=from_cursor,
    )


def _run_wind_sequence(
    tables: tuple[str, ...],
    *,
    write_db: bool,
    page_size: int,
    max_pages: int | None,
    from_cursor: str | None,
) -> None:
    if from_cursor is not None:
        typer.secho("按顺序同步多张表时不能传 --from-cursor", fg=typer.colors.RED, err=True)
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
            f"rows={result.row_count} replaced={result.replaced} deleted={result.deleted} "
            f"metadata_skipped={result.metadata_skipped} "
            f"dml={result.dml_count} cursor={result.source_cursor}"
        )


@wind_app.command("verify")
def ingest_wind_verify(
    table: Annotated[str, typer.Argument(help="Wind 表名，如 AINDEXEODPRICES")],
) -> None:
    """只读：用库里的值重算 _row_hash，与写入时的指纹比对。不一致即退出码 1。"""
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    try:
        result = verify_wind_table(settings=settings, paths=paths, table=table)
    except (IngestError, ConfigError, RunLogError, PostgresAdapterError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"dataset={result.dataset} rows={result.row_count} mismatched={result.mismatched} "
        f"type_only={result.type_only} "
        f"samples={list(result.samples)}"
    )
    if result.mismatched:
        raise typer.Exit(code=1)


@wind_app.command("progress")
def ingest_wind_progress(
    window: Annotated[int, typer.Option("--window", min=1, help="统计最近 N 分钟的页速")] = 60,
    stale: Annotated[
        int, typer.Option("--stale", min=1, help="距上次提交超过 N 分钟且近窗口有页时标 STALE")
    ] = 15,
) -> None:
    """只读：按表汇总 src_wind._batch，查看回填进度与是否卡住。"""
    settings = get_settings()
    try:
        with connect(settings, "src") as conn:
            rows = wind_progress(conn, window_minutes=window)
    except (ConfigError, PostgresAdapterError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    now = datetime.now(UTC)
    typer.echo(
        f"{'dataset':38} {'pages':>7} {'rows':>12} {'last_commit':>19} {'idle_min':>8} "
        f"{'s/page':>7}  flag"
    )
    for item in rows:
        idle = (now - item.last_commit).total_seconds() / 60
        # 只对“近窗口还在出页、但最近一段没动静”的表报警；早已追平的表闲着是正常的。
        flag = "STALE" if item.recent_pages and idle > stale else ""
        speed = (
            "" if item.recent_seconds_per_page is None else f"{item.recent_seconds_per_page:.1f}"
        )
        typer.echo(
            f"{item.dataset:38} {item.pages:7d} {item.rows:12,d} "
            f"{item.last_commit.astimezone().strftime('%Y-%m-%d %H:%M:%S'):>19} "
            f"{idle:8.1f} {speed:>7}  {flag}"
        )
