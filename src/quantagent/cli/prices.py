"""``quantagent prices``：研究读取日行情。必须带 --as-of。"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated

import typer

from quantagent.adapters.postgres.daily_prices import (
    PostgresDailyPriceRepository,
    load_price_visibility,
)
from quantagent.domain.errors import DomainError
from quantagent.platform.config import get_settings
from quantagent.platform.errors import ConfigError
from quantagent.platform.pg import connect

if TYPE_CHECKING:
    from decimal import Decimal

prices_app = typer.Typer(help="日行情研究读取。必须传 --as-of。", no_args_is_help=True)


@prices_app.command("window")
def prices_window(
    *,
    start: Annotated[str, typer.Option("--start", help="窗口起点 YYYY-MM-DD")],
    end: Annotated[str, typer.Option("--end", help="窗口终点 YYYY-MM-DD")],
    codes: Annotated[str, typer.Option("--codes", help="逗号分隔的 Wind 代码")],
    as_of: Annotated[str, typer.Option("--as-of", help="可见日 YYYY-MM-DD，必填")],
) -> None:
    start_dt = _parse_ymd(start, "--start")
    end_dt = _parse_ymd(end, "--end")
    as_of_dt = _parse_ymd(as_of, "--as-of")
    wind_codes = tuple(part.strip() for part in codes.split(",") if part.strip())
    settings = get_settings()
    try:
        conn = connect(settings, "src")
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    try:
        rows = PostgresDailyPriceRepository(conn).list_prices(
            as_of=as_of_dt,
            start=start_dt,
            end=end_dt,
            wind_codes=wind_codes,
        )
    except (DomainError, ConfigError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    finally:
        conn.close()
    vis = load_price_visibility().visibility
    typer.echo(f"n={len(rows)} as_of={as_of_dt.isoformat()} pit={vis.rule}/{vis.grade}")
    for row in rows:
        typer.echo(
            f"{row.trade_dt.isoformat()} {row.wind_code} "
            f"open={_num(row.open)} high={_num(row.high)} low={_num(row.low)} "
            f"close={_num(row.close)} volume={_num(row.volume)} "
            f"amount={_num(row.amount)} pct={_num(row.pct_change)}"
        )


def _parse_ymd(raw: str, flag: str) -> date:
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise typer.BadParameter(f"{flag} 必须是 YYYY-MM-DD", param_hint=flag) from exc


def _num(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value, "f")
