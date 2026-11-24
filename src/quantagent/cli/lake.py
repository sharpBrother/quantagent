"""``quantagent lake`` 分组：物化与布局 benchmark。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from quantagent.adapters.postgres.errors import PostgresAdapterError
from quantagent.cli.cutamp_materialize import materialize_cutamp
from quantagent.cli.forward_return_materialize import materialize_forward_return_cli
from quantagent.cli.mif_materialize import materialize_mif
from quantagent.cli.minute_factors_2b_materialize import materialize_minute_factors_2b
from quantagent.cli.minute_factors_materialize import materialize_minute_factors
from quantagent.cli.moneyflow_materialize import materialize_moneyflow_factors
from quantagent.cli.tr_umr_materialize import materialize_tr_umr
from quantagent.domain.errors import DomainError
from quantagent.lake.layout_bench import SCALES, run_layout_benchmark
from quantagent.lake.materialize.trade_calendar import materialize_trade_calendar
from quantagent.lake.partitions import LakeLayoutError
from quantagent.platform.config import get_settings
from quantagent.platform.errors import ConfigError, DuckSessionError, RunLogError
from quantagent.platform.identity import digest_json
from quantagent.platform.runlog import RunLog, persist_run_log
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

if TYPE_CHECKING:
    from quantagent.platform.storage.paths import VarPaths

lake_app = typer.Typer(help="Parquet 湖：物化与布局 benchmark。", no_args_is_help=True)
materialize_app = typer.Typer(help="标准化 / 口径表物化。", no_args_is_help=True)
lake_app.add_typer(materialize_app, name="materialize")


@lake_app.command("benchmark-layout")
def lake_benchmark_layout(
    scale: Annotated[str, typer.Option("--scale", help="tiny 或 paper")] = "tiny",
    rebuild: Annotated[bool, typer.Option("--rebuild", help="允许覆盖已有合成布局")] = False,
    repeats: Annotated[int, typer.Option("--repeats", min=1)] = 5,
    root: Annotated[str | None, typer.Option("--root", help="合成 parquet 输出目录")] = None,
    out: Annotated[str | None, typer.Option("--out", help="报告 JSON 路径")] = None,
) -> None:
    """用合成 feature.value 比较分区 / 排序 / 压缩，写出 JSON 报告。"""
    if scale not in SCALES:
        typer.secho(f"未知 scale: {scale}（tiny / paper）", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    settings = get_settings()
    repo_root = detect_repo_root()
    paths = resolve_var_paths(settings, repo_root=repo_root)
    dest = Path(root) if root else paths.cache / "feature_layout_bench" / scale
    report_path = Path(out) if out else dest / "report.json"
    started = datetime.now(UTC)
    try:
        report = run_layout_benchmark(root=dest, scale=scale, repeats=repeats, rebuild=rebuild)
    except (LakeLayoutError, DuckSessionError, ValueError) as exc:
        _persist_failure(
            paths=paths,
            started=started,
            scale=scale,
            dest=dest,
            error=str(exc),
        )
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if report_path.exists() and not rebuild:
        typer.secho(f"拒绝覆盖已有报告: {report_path}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    finished = datetime.now(UTC)
    record = RunLog(
        action="lake.benchmark-layout",
        status="success",
        started_at=started,
        finished_at=finished,
        elapsed_ms=int((finished - started).total_seconds() * 1000),
        input_digest=digest_json({"scale": scale, "repeats": repeats, "root": dest.as_posix()}),
        output_digest=str(report["digest"]),
        row_count=int(report["n_rows"]),
        dml_count=0,
    )
    try:
        persist_run_log(record, paths)
    except RunLogError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(report, indent=2, ensure_ascii=False))
    typer.echo(f"report {report_path}")


@materialize_app.command("trade-calendar")
def lake_materialize_trade_calendar(
    as_of: Annotated[str, typer.Option("--as-of", help="物化运行日 YYYY-MM-DD，只写入 run log")],
    rebuild: Annotated[bool, typer.Option("--rebuild", help="允许覆盖已有 parquet")] = False,
    horizon_days: Annotated[
        int | None,
        typer.Option("--horizon-days", min=0, help="只保留 cal_dt <= as_of + N 天的行"),
    ] = None,
    append_only: Annotated[
        bool,
        typer.Option("--append-only", help="只追加快照里新出现的日期，不改既有分片"),
    ] = False,
) -> None:
    """将 Wind 日历快照物化为 std.trade_calendar，供按 as_of 读取。"""
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    try:
        as_of_date = datetime.strptime(as_of.strip(), "%Y-%m-%d").date()
        result = materialize_trade_calendar(
            settings=settings,
            paths=paths,
            as_of=as_of_date,
            rebuild=rebuild,
            append_only=append_only,
            horizon_days=horizon_days,
        )
    except (LakeLayoutError, PostgresAdapterError, ConfigError, RunLogError, ValueError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"wrote dataset={result.dataset} rows={result.row_count} "
        f"appended={result.appended} digest={result.output_digest} path={result.path}"
    )


@materialize_app.command("cutamp")
def lake_materialize_cutamp(
    start: Annotated[str, typer.Option("--start", help="截面起点 YYYY-MM-DD")],
    end: Annotated[str, typer.Option("--end", help="截面终点 YYYY-MM-DD")],
    codes: Annotated[str, typer.Option("--codes", help="逗号分隔的 Wind 代码")],
    as_of: Annotated[str, typer.Option("--as-of", help="行情可见日 YYYY-MM-DD，必填")],
) -> None:
    """把切段振幅写入 feature.value。窗口不足的日期不落行。"""
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    wind_codes = tuple(part.strip() for part in codes.split(",") if part.strip())
    try:
        row_count, digest = materialize_cutamp(
            settings=settings,
            paths=paths,
            start=datetime.strptime(start.strip(), "%Y-%m-%d").date(),
            end=datetime.strptime(end.strip(), "%Y-%m-%d").date(),
            wind_codes=wind_codes,
            as_of=datetime.strptime(as_of.strip(), "%Y-%m-%d").date(),
        )
    except (
        LakeLayoutError,
        DomainError,
        PostgresAdapterError,
        ConfigError,
        RunLogError,
        ValueError,
    ) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"wrote dataset=feature.value rows={row_count} digest={digest}")


@materialize_app.command("minute-factors-2b")
def lake_materialize_minute_factors_2b(
    start: Annotated[str, typer.Option("--start", help="截面起点 YYYY-MM-DD")],
    end: Annotated[str, typer.Option("--end", help="截面终点 YYYY-MM-DD")],
    as_of: Annotated[str, typer.Option("--as-of", help="分钟行情可见日 YYYY-MM-DD，必填")],
    feature: Annotated[
        list[str],
        typer.Option(
            "--feature",
            help=(
                "要产出的因子 id，可重复。pf_single_corr_vrlaglarge_5_mean_neg、"
                "pf_single_core_up_20_mean_pos_neut_pxret21、"
                "pf_single_core_down_20_mean_neg_neut_pxret21"
            ),
        ),
    ],
    codes: Annotated[
        str | None,
        typer.Option("--codes", help="逗号分隔的 Wind 代码；不传则每个截面日取该日 all_a 成员"),
    ] = None,
) -> None:
    """把 Current-20 第二批的三个分钟因子写入 feature.value。
    中性化因子在每个截面日做 pxret21 截面回归残差。排除日与缺失规则同第一批。
    """
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    code_tuple = (
        None if codes is None else tuple(part.strip() for part in codes.split(",") if part.strip())
    )
    try:
        row_count, digest = materialize_minute_factors_2b(
            settings=settings,
            paths=paths,
            start=datetime.strptime(start.strip(), "%Y-%m-%d").date(),
            end=datetime.strptime(end.strip(), "%Y-%m-%d").date(),
            as_of=datetime.strptime(as_of.strip(), "%Y-%m-%d").date(),
            codes=code_tuple,
            feature_ids=tuple(feature),
        )
    except (
        LakeLayoutError,
        DomainError,
        PostgresAdapterError,
        ConfigError,
        RunLogError,
        ValueError,
    ) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"wrote dataset=feature.value rows={row_count} digest={digest}")


@materialize_app.command("minute-factors")
def lake_materialize_minute_factors(
    start: Annotated[str, typer.Option("--start", help="截面起点 YYYY-MM-DD")],
    end: Annotated[str, typer.Option("--end", help="截面终点 YYYY-MM-DD")],
    as_of: Annotated[str, typer.Option("--as-of", help="分钟行情可见日 YYYY-MM-DD，必填")],
    codes: Annotated[
        str | None,
        typer.Option("--codes", help="逗号分隔的 Wind 代码；不传则每个截面日取该日 all_a 成员"),
    ] = None,
) -> None:
    """把 Current-20 的四个分钟因子（5 日均值，方向 -1）写入 feature.value。

    分区被排除的股票在排除日没有日值，不进入五日均值，运行不中断。
    """
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    code_tuple = (
        None if codes is None else tuple(part.strip() for part in codes.split(",") if part.strip())
    )
    try:
        row_count, digest = materialize_minute_factors(
            settings=settings,
            paths=paths,
            start=datetime.strptime(start.strip(), "%Y-%m-%d").date(),
            end=datetime.strptime(end.strip(), "%Y-%m-%d").date(),
            as_of=datetime.strptime(as_of.strip(), "%Y-%m-%d").date(),
            codes=code_tuple,
        )
    except (
        LakeLayoutError,
        DomainError,
        PostgresAdapterError,
        ConfigError,
        RunLogError,
        ValueError,
    ) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"wrote dataset=feature.value rows={row_count} digest={digest}")


@materialize_app.command("moneyflow-factors")
def lake_materialize_moneyflow_factors(
    start: Annotated[str, typer.Option("--start", help="截面起点 YYYY-MM-DD")],
    end: Annotated[str, typer.Option("--end", help="截面终点 YYYY-MM-DD")],
    as_of: Annotated[str, typer.Option("--as-of", help="行情与资金流可见日 YYYY-MM-DD，必填")],
    codes: Annotated[
        str | None,
        typer.Option("--codes", help="逗号分隔的 Wind 代码；不传则取截面日 end 的 all_a 成员"),
    ] = None,
) -> None:
    """把 abso_umr、moneyflowh、actlargemedcut 三个资金流因子写入 feature.value。
    窗口不足或缺失输入的股票不落行。
    """
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    code_tuple = (
        None if codes is None else tuple(part.strip() for part in codes.split(",") if part.strip())
    )
    try:
        row_count, digest = materialize_moneyflow_factors(
            settings=settings,
            paths=paths,
            start=datetime.strptime(start.strip(), "%Y-%m-%d").date(),
            end=datetime.strptime(end.strip(), "%Y-%m-%d").date(),
            wind_codes=code_tuple,
            as_of=datetime.strptime(as_of.strip(), "%Y-%m-%d").date(),
        )
    except (
        LakeLayoutError,
        DomainError,
        PostgresAdapterError,
        ConfigError,
        RunLogError,
        ValueError,
    ) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"wrote dataset=feature.value rows={row_count} digest={digest}")


@materialize_app.command("mif")
def lake_materialize_mif(
    start: Annotated[str, typer.Option("--start", help="截面起点 YYYY-MM-DD")],
    end: Annotated[str, typer.Option("--end", help="截面终点 YYYY-MM-DD")],
    as_of: Annotated[str, typer.Option("--as-of", help="行情与衍生指标可见日 YYYY-MM-DD，必填")],
    codes: Annotated[
        str | None,
        typer.Option("--codes", help="逗号分隔的 Wind 代码；不传则每个截面日取该日 all_a 成员"),
    ] = None,
) -> None:
    """把 pf_single_mif_1_mean_neg（隔夜信息与换手相关，方向 -1）写入 feature.value。
    窗口不足、停牌或换手缺失的股票不落行。
    """
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    code_tuple = (
        None if codes is None else tuple(part.strip() for part in codes.split(",") if part.strip())
    )
    try:
        row_count, digest = materialize_mif(
            settings=settings,
            paths=paths,
            start=datetime.strptime(start.strip(), "%Y-%m-%d").date(),
            end=datetime.strptime(end.strip(), "%Y-%m-%d").date(),
            wind_codes=code_tuple,
            as_of=datetime.strptime(as_of.strip(), "%Y-%m-%d").date(),
        )
    except (
        LakeLayoutError,
        DomainError,
        PostgresAdapterError,
        ConfigError,
        RunLogError,
        ValueError,
    ) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"wrote dataset=feature.value rows={row_count} digest={digest}")


@materialize_app.command("tr-umr")
def lake_materialize_tr_umr(
    start: Annotated[str, typer.Option("--start", help="截面起点 YYYY-MM-DD")],
    end: Annotated[str, typer.Option("--end", help="截面终点 YYYY-MM-DD")],
    codes: Annotated[str, typer.Option("--codes", help="逗号分隔的 Wind 代码")],
    as_of: Annotated[str, typer.Option("--as-of", help="行情可见日 YYYY-MM-DD，必填")],
) -> None:
    """把真实波幅 UMR 写入 feature.value。窗口不足的日期不落行。"""
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    wind_codes = tuple(part.strip() for part in codes.split(",") if part.strip())
    try:
        row_count, digest = materialize_tr_umr(
            settings=settings,
            paths=paths,
            start=datetime.strptime(start.strip(), "%Y-%m-%d").date(),
            end=datetime.strptime(end.strip(), "%Y-%m-%d").date(),
            wind_codes=wind_codes,
            as_of=datetime.strptime(as_of.strip(), "%Y-%m-%d").date(),
        )
    except (
        LakeLayoutError,
        DomainError,
        PostgresAdapterError,
        ConfigError,
        RunLogError,
        ValueError,
    ) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"wrote dataset=feature.value rows={row_count} digest={digest}")


@materialize_app.command("forward-return")
def lake_materialize_forward_return(
    start: Annotated[str, typer.Option("--start", help="信号日起点 YYYY-MM-DD")],
    end: Annotated[str, typer.Option("--end", help="信号日终点 YYYY-MM-DD")],
    as_of: Annotated[str, typer.Option("--as-of", help="行情可见日 YYYY-MM-DD，必填")],
    codes: Annotated[
        str | None,
        typer.Option("--codes", help="逗号分隔的 Wind 代码；省略则取 all_a 池成员"),
    ] = None,
) -> None:
    """把 open-to-open 前瞻收益写入 mart.forward_return。区间不成熟或端点停牌的行不落行。"""
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    wind_codes: tuple[str, ...] | None = None
    if codes is not None:
        wind_codes = tuple(part.strip() for part in codes.split(",") if part.strip())
    try:
        result = materialize_forward_return_cli(
            settings=settings,
            paths=paths,
            start=datetime.strptime(start.strip(), "%Y-%m-%d").date(),
            end=datetime.strptime(end.strip(), "%Y-%m-%d").date(),
            as_of=datetime.strptime(as_of.strip(), "%Y-%m-%d").date(),
            wind_codes=wind_codes,
        )
    except (
        LakeLayoutError,
        DomainError,
        PostgresAdapterError,
        ConfigError,
        DuckSessionError,
        RunLogError,
        ValueError,
    ) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"wrote dataset=mart.forward_return rows={result.row_count} "
        f"files={result.n_files} digest={result.digest}"
    )


def _persist_failure(
    *,
    paths: VarPaths,
    started: datetime,
    scale: str,
    dest: Path,
    error: str,
) -> None:
    finished = datetime.now(UTC)
    record = RunLog(
        action="lake.benchmark-layout",
        status="failure",
        started_at=started,
        finished_at=finished,
        elapsed_ms=int((finished - started).total_seconds() * 1000),
        input_digest=digest_json({"scale": scale, "root": dest.as_posix()}),
        error=error,
        dml_count=0,
    )
    try:
        persist_run_log(record, paths)
    except RunLogError:
        return
