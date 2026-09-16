"""``quantagent db`` 分组：双面 migrate / status。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from quantagent.adapters.postgres.errors import MigrationError
from quantagent.adapters.postgres.migrate import (
    apply_migrations,
    collect_status,
    resolve_planes,
)
from quantagent.platform.config import get_settings
from quantagent.platform.errors import ConfigError, WriteGateError
from quantagent.platform.pg import plane_configured
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

if TYPE_CHECKING:
    from quantagent.platform.config.settings import Settings
    from quantagent.platform.pg import Plane

db_app = typer.Typer(help="数据库迁移与状态。", no_args_is_help=True)


@db_app.command("status")
def db_status() -> None:
    """显示 profile、写闸、PG 配置，以及各面已应用 / 待应用的迁移。"""
    settings = get_settings()
    repo_root = detect_repo_root()
    paths = resolve_var_paths(settings, repo_root=repo_root)
    typer.echo(f"profile          {settings.profile}")
    typer.echo(f"var_root         {paths.root}")
    typer.echo(f"allow_db_write   {str(settings.allow_db_write).lower()}")
    typer.echo(f"pg src           {_pg_endpoint(settings, 'src')}")
    typer.echo(f"pg ops           {_pg_endpoint(settings, 'ops')}")
    try:
        reports = collect_status(settings=settings, repo_root=repo_root)
    except (MigrationError, ConfigError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    for report in reports:
        if not plane_configured(settings, report.plane):
            typer.echo(f"pg {report.plane} migrate   未配置（磁盘 {len(report.pending)} 个文件）")
            continue
        typer.echo(
            f"pg {report.plane} migrate   "
            f"applied={len(report.applied)} pending={len(report.pending)}"
        )


@db_app.command("migrate")
def db_migrate(
    plane: str = typer.Option("all", "--plane", help="src、ops 或 all"),
    write_db: bool = typer.Option(False, "--write-db", help="显式允许写库"),
) -> None:
    """按面应用编号 SQL。默认干跑；真正执行需要 --write-db 且写闸打开。"""
    settings = get_settings()
    repo_root = detect_repo_root()
    try:
        planes = resolve_planes(plane)
        reports = apply_migrations(
            settings=settings,
            repo_root=repo_root,
            planes=planes,
            write_db=write_db,
        )
    except (MigrationError, ConfigError, WriteGateError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    for report in reports:
        typer.echo(
            f"{report.plane}  applied={len(report.applied)} "
            f"pending={len(report.pending)} applied_now={len(report.applied_now)} "
            f"statements={report.statement_count}"
        )
        for filename in report.pending:
            typer.echo(f"{report.plane}  pending {filename}")
        for filename in report.applied_now:
            typer.echo(f"{report.plane}  applied {filename}")
    if not write_db:
        typer.secho("拒绝写库：未传 --write-db", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


def _pg_endpoint(settings: Settings, plane: Plane) -> str:
    if plane == "src":
        if not settings.pg_src_configured:
            return "未配置"
        return (
            f"{settings.pg_src_user}@{settings.pg_src_host}:"
            f"{settings.pg_src_port}/{settings.pg_src_database}"
        )
    if not settings.pg_ops_configured:
        return "未配置"
    return (
        f"{settings.pg_ops_user}@{settings.pg_ops_host}:"
        f"{settings.pg_ops_port}/{settings.pg_ops_database}"
    )
