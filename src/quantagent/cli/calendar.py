"""``quantagent calendar``：研究读取交易日历。必须带 --as-of。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

import typer

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.domain.calendar.queries import CalendarQueries
from quantagent.domain.errors import DomainError
from quantagent.platform.config import get_settings
from quantagent.platform.errors import ConfigError
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

calendar_app = typer.Typer(help="交易日历研究读取。必须传 --as-of。", no_args_is_help=True)

# 与采集默认窗口下界对齐，作为 CLI 的 observed domain；不是把缺失日期填成 1990。
_OBS_START = date(1990, 1, 1)


@calendar_app.command("is-open")
def calendar_is_open(
    exchange: Annotated[str, typer.Option("--exchange")],
    cal_dt: Annotated[str, typer.Option("--cal-dt", help="业务日 YYYY-MM-DD")],
    as_of: Annotated[str, typer.Option("--as-of", help="可见日 YYYY-MM-DD，必填")],
) -> None:
    queries = _queries()
    day = _parse_ymd(cal_dt, "--cal-dt")
    as_of_dt = _parse_ymd(as_of, "--as-of")
    try:
        opened = queries.is_open(exchange=exchange, cal_dt=day, as_of=as_of_dt)
    except (DomainError, ConfigError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"exchange={exchange} cal_dt={day.isoformat()} as_of={as_of_dt.isoformat()} "
        f"is_open={str(opened).lower()} pit=same_day_close/A"
    )


@calendar_app.command("shift")
def calendar_shift(
    exchange: Annotated[str, typer.Option("--exchange")],
    origin: Annotated[str, typer.Option("--origin", help="起点日 YYYY-MM-DD")],
    n: Annotated[int, typer.Option("--n", help="T+n，0 要求当日开市")],
    as_of: Annotated[str, typer.Option("--as-of", help="可见日 YYYY-MM-DD，必填")],
) -> None:
    queries = _queries()
    origin_dt = _parse_ymd(origin, "--origin")
    as_of_dt = _parse_ymd(as_of, "--as-of")
    try:
        shifted = queries.shift(
            exchange=exchange,
            origin=origin_dt,
            n=n,
            as_of=as_of_dt,
            start=_OBS_START,
            end=as_of_dt,
        )
    except (DomainError, ConfigError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"exchange={exchange} origin={origin_dt.isoformat()} n={n} "
        f"as_of={as_of_dt.isoformat()} result={shifted.isoformat()} pit=same_day_close/A"
    )


def _queries() -> CalendarQueries:
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    repo = LakeCalendarRepository(paths.lake / "std" / "trade_calendar")
    return CalendarQueries(repo)


def _parse_ymd(raw: str, flag: str) -> date:
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise typer.BadParameter(f"{flag} 必须是 YYYY-MM-DD", param_hint=flag) from exc
