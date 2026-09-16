"""``quantagent check`` 分组。"""

from __future__ import annotations

import typer

from quantagent.contracts.check import run_check
from quantagent.contracts.errors import ContractError
from quantagent.platform.storage import detect_repo_root

check_app = typer.Typer(help="契约与一致性校验。", no_args_is_help=True)


@check_app.command("contracts")
def check_contracts() -> None:
    """校验 schema、可见性规则完整性与文档双向绑定。缺规则即失败。"""
    try:
        report = run_check(repo_root=detect_repo_root())
    except ContractError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    if report.ok:
        typer.echo("contracts: ok")
        return
    for issue in report.issues:
        typer.secho(issue.render(), fg=typer.colors.RED, err=True)
    typer.secho(f"contracts: {len(report.issues)} 个问题", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)
