"""``quantagent group-nav``：研究读取因子分组净值。必须带 --as-of。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

import typer

from quantagent.adapters.lake.group_nav import LakeGroupNavRepository
from quantagent.adapters.lake.visibility import load_dataset_visibility
from quantagent.domain.errors import DomainError
from quantagent.platform.config import get_settings
from quantagent.platform.errors import ConfigError, DuckSessionError
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

group_nav_app = typer.Typer(help="分组净值研究读取。必须传 --as-of。", no_args_is_help=True)


@group_nav_app.command("window")
def group_nav_window(
    *,
    feature_id: Annotated[str, typer.Option("--feature-id")],
    definition_version: Annotated[str, typer.Option("--definition-version")],
    param_hash: Annotated[str, typer.Option("--param-hash")],
    universe_id: Annotated[str, typer.Option("--universe-id")],
    horizon: Annotated[str, typer.Option("--horizon")],
    run_id: Annotated[str, typer.Option("--run-id")],
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
            feature_id=feature_id,
            definition_version=definition_version,
            param_hash=param_hash,
            universe_id=universe_id,
            horizon=horizon,
            run_id=run_id,
            start=start_dt,
            end=end_dt,
        )
    except (DomainError, ConfigError, DuckSessionError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"n={len(rows)} as_of={as_of_dt.isoformat()} {_pit_tag()}")
    for row in rows:
        typer.echo(
            f"{row.event_dt.isoformat()} g={row.group_no} {row.group_nav} "
            f"{row.knowledge_dt.isoformat()}"
        )


def _repo() -> LakeGroupNavRepository:
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    return LakeGroupNavRepository(paths.lake / "signal" / "group_nav")


def _pit_tag() -> str:
    vis = load_dataset_visibility("signal.group_nav").visibility
    return f"pit={vis.rule}/{vis.grade}"


def _parse_ymd(raw: str, flag: str) -> date:
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise typer.BadParameter(f"{flag} 必须是 YYYY-MM-DD", param_hint=flag) from exc
