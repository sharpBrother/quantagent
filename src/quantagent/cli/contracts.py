"""``quantagent contracts`` 分组：从契约派生产物。校验请用 ``quantagent check``。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from quantagent.contracts.errors import ContractError
from quantagent.ingest.writers.column_comments import (
    ColumnCommentError,
    build_column_comments,
    render_comment_sql,
)

contracts_app = typer.Typer(help="从契约派生产物。", no_args_is_help=True)


@contracts_app.command("emit-comments")
def emit_comments(
    out: Annotated[str, typer.Option("--out", help="输出的迁移 SQL 路径")],
) -> None:
    """从契约 YAML 的 description 生成 COMMENT ON COLUMN 语句，写入 --out。"""
    try:
        comments = build_column_comments()
    except (ColumnCommentError, ContractError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    target = Path(out)
    target.write_text(render_comment_sql(comments), encoding="utf-8")
    typer.echo(f"emit-comments: {len(comments)} 条 -> {target}")
