"""CLI 根应用。子命令只做参数解析、组装依赖、调用业务函数。"""

from __future__ import annotations

import typer

from quantagent.cli.check import check_app
from quantagent.cli.db import db_app
from quantagent.cli.lake import lake_app
from quantagent.platform.logging import configure_logging

app = typer.Typer(
    name="quantagent",
    help="QuantAgent：量化投研系统。入口只有 CLI 与 Dagster，没有 scripts/。",
    no_args_is_help=True,
)
app.add_typer(check_app, name="check", help="契约与一致性校验")
app.add_typer(db_app, name="db", help="数据库迁移与状态")
app.add_typer(lake_app, name="lake", help="Parquet 湖物化与布局 benchmark")


@app.callback()
def _root() -> None:
    """QuantAgent CLI。"""
    configure_logging()
