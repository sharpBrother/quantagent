"""``quantagent universe``：研究读取股票池成员。必须带 --as-of。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

import typer

from quantagent.adapters.lake.universe_member import LakeUniverseRepository
from quantagent.adapters.lake.visibility import load_dataset_visibility
from quantagent.domain.errors import DomainError
from quantagent.platform.config import get_settings
from quantagent.platform.errors import ConfigError, DuckSessionError
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

universe_app = typer.Typer(help="股票池成员研究读取。必须传 --as-of。", no_args_is_help=True)


@universe_app.command("members")
def universe_members(
    *,
    universe_id: Annotated[str, typer.Option("--universe-id")],
    dt: Annotated[str, typer.Option("--dt", help="成员日 YYYY-MM-DD")],
    as_of: Annotated[str, typer.Option("--as-of", help="可见日 YYYY-MM-DD，必填")],
) -> None:
    repo = _repo()
    dt_day = _parse_ymd(dt, "--dt")
    as_of_dt = _parse_ymd(as_of, "--as-of")
    try:
        rows = repo.members_at(as_of=as_of_dt, dt=dt_day, universe_id=universe_id)
    except (DomainError, ConfigError, DuckSessionError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"n={len(rows)} as_of={as_of_dt.isoformat()} {_pit_tag()}")
    for row in rows:
        valid_to = "" if row.valid_to is None else row.valid_to.isoformat()
        typer.echo(f"{row.asset_id} {row.valid_from.isoformat()} {valid_to}")


def _repo() -> LakeUniverseRepository:
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    return LakeUniverseRepository(paths.lake / "mart" / "universe_member")


def _pit_tag() -> str:
    vis = load_dataset_visibility("mart.universe_member").visibility
    return f"pit={vis.rule}/{vis.grade}"


def _parse_ymd(raw: str, flag: str) -> date:
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise typer.BadParameter(f"{flag} 必须是 YYYY-MM-DD", param_hint=flag) from exc
