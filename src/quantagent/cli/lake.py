"""``quantagent lake`` 分组：物化与布局 benchmark。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

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
) -> None:
    """把 src_tushare.trade_cal 改名/转类型写入 std.trade_calendar。不按 cal_dt 截断。"""
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    try:
        as_of_date = datetime.strptime(as_of.strip(), "%Y-%m-%d").date()
        result = materialize_trade_calendar(
            settings=settings,
            paths=paths,
            as_of=as_of_date,
            rebuild=rebuild,
        )
    except (LakeLayoutError, ConfigError, RunLogError, ValueError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"wrote dataset={result.dataset} rows={result.row_count} "
        f"digest={result.output_digest} path={result.path}"
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
