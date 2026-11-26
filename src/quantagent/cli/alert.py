"""``quantagent alert``：失败告警的每日汇总。

sensor 只感知失败事件并落 JSONL；汇总把前一自然日的记录按作业分组写成
``var/logs/alerts/summary/YYYY-MM-DD.json`` 并打印可读版。通知渠道（邮件/企业微信）
负责人尚未裁定，汇总先供人肉查看；渠道接入后从同一汇总文件消费。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Annotated

import typer

from quantagent.platform.alerts import (
    build_daily_summary,
    read_failure_alerts,
    write_daily_summary,
)
from quantagent.platform.config import get_settings
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

if TYPE_CHECKING:
    from pathlib import Path

alert_app = typer.Typer(
    help="失败告警汇总。读取 var/logs/alerts/run_failures.jsonl。",
    no_args_is_help=True,
)


def _alerts_dir() -> Path:
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    return paths.logs / "alerts"


@alert_app.command("summary")
def alert_summary(
    day: Annotated[
        str | None,
        typer.Option("--day", help="汇总日 YYYY-MM-DD；缺省为昨天（UTC）"),
    ] = None,
) -> None:
    """生成某一自然日的失败汇总。窗口按 UTC 自然日切，与 run log 时间戳同轴。"""
    if day is None:
        target = date.today() - timedelta(days=1)
    else:
        try:
            target = datetime.strptime(day, "%Y-%m-%d").date()
        except ValueError as exc:
            typer.secho(f"--day 必须是 YYYY-MM-DD: {day}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from exc
    start = datetime(target.year, target.month, target.day, tzinfo=UTC)
    end = start + timedelta(days=1)

    alerts_dir = _alerts_dir()
    jsonl = alerts_dir / "run_failures.jsonl"
    # 前闭后开：边界时刻的记录只属于一个自然日。
    alerts = [
        alert
        for alert in read_failure_alerts(jsonl, since=start)
        if datetime.fromisoformat(alert.recorded_at) < end
    ]
    summary = build_daily_summary(alerts, day=target.isoformat())
    dest = alerts_dir / "summary" / f"{target.isoformat()}.json"
    write_daily_summary(summary, dest)

    if not alerts:
        typer.echo(f"{target.isoformat()} 无异常（0 条失败记录）→ {dest}")
        return
    typer.secho(
        f"{target.isoformat()} 有异常：{len(alerts)} 条失败记录 → {dest}",
        fg=typer.colors.YELLOW,
    )
    jobs = summary["jobs"]
    assert isinstance(jobs, dict)
    for job, entries in jobs.items():
        typer.echo(f"  {job}: {len(entries)} 次")
        for entry in entries:
            typer.echo(f"    {entry['recorded_at']} {entry['failure_message']}")
