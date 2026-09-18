"""``quantagent forward-return``：研究读取前瞻收益。必须带 --as-of。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

import typer

from quantagent.adapters.lake.forward_return import LakeForwardReturnRepository
from quantagent.adapters.lake.visibility import load_dataset_visibility
from quantagent.domain.errors import DomainError
from quantagent.platform.config import get_settings
from quantagent.platform.errors import ConfigError, DuckSessionError
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

forward_return_app = typer.Typer(
    help="前瞻收益研究读取。evaluation_only，必须传 --as-of。",
    no_args_is_help=True,
)


@forward_return_app.command("window")
def forward_return_window(
    *,
    horizon: Annotated[str, typer.Option("--horizon")],
    return_kind: Annotated[str, typer.Option("--return-kind")],
    benchmark_id: Annotated[str, typer.Option("--benchmark-id")],
    start: Annotated[str, typer.Option("--start", help="窗口起点 YYYY-MM-DD")],
    end: Annotated[str, typer.Option("--end", help="窗口终点 YYYY-MM-DD")],
    as_of: Annotated[str, typer.Option("--as-of", help="可见日 YYYY-MM-DD，必填")],
) -> None:
    repo = _repo()
    start_dt = _parse_ymd(start, "--start")
    end_dt = _parse_ymd(end, "--end")
    as_of_dt = _parse_ymd(as_of, "--as-of")
    try:
        rows = repo.scan_window(
            as_of=as_of_dt,
            horizon=horizon,
            return_kind=return_kind,
            benchmark_id=benchmark_id,
            start=start_dt,
            end=end_dt,
        )
    except (DomainError, ConfigError, DuckSessionError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"n={len(rows)} as_of={as_of_dt.isoformat()} {_pit_tag()}")
    for row in rows:
        typer.echo(
            f"{row.asset_id} {row.event_dt.isoformat()} {row.value} {row.knowledge_dt.isoformat()}"
        )


def _repo() -> LakeForwardReturnRepository:
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    return LakeForwardReturnRepository(paths.lake / "mart" / "forward_return")


def _pit_tag() -> str:
    vis = load_dataset_visibility("mart.forward_return").visibility
    return f"pit={vis.rule}/{vis.grade}"


def _parse_ymd(raw: str, flag: str) -> date:
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise typer.BadParameter(f"{flag} 必须是 YYYY-MM-DD", param_hint=flag) from exc
