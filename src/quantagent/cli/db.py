"""``quantagent db`` 分组。第一刀只报告配置是否齐全，不连库、不迁移。"""

from __future__ import annotations

import typer

from quantagent.platform.config import get_settings
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

db_app = typer.Typer(help="数据库迁移与状态。", no_args_is_help=True)


@db_app.command("status")
def db_status() -> None:
    """显示 profile、var 根路径、写闸和 PG 是否已配置。未配置不视为错误。"""
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    src = _pg_status(
        settings.pg_src_configured,
        settings.pg_src_user,
        settings.pg_src_host,
        settings.pg_src_port,
        settings.pg_src_database,
    )
    ops = _pg_status(
        settings.pg_ops_configured,
        settings.pg_ops_user,
        settings.pg_ops_host,
        settings.pg_ops_port,
        settings.pg_ops_database,
    )
    typer.echo(f"profile          {settings.profile}")
    typer.echo(f"var_root         {paths.root}")
    typer.echo(f"allow_db_write   {str(settings.allow_db_write).lower()}")
    typer.echo(f"pg src           {src}")
    typer.echo(f"pg ops           {ops}")


def _pg_status(configured: bool, user: str, host: str, port: int, database: str) -> str:
    if not configured:
        return "未配置"
    return f"{user}@{host}:{port}/{database}"
