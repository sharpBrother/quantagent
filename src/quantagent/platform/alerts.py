"""失败告警落盘。

通知渠道（邮件 / 企业微信）等负责人裁定后再加；告警内容不能等——11-25 jydb 卡死
7 小时堵住单并发队列，靠人工发现。先把每条 run 失败与每日汇总落成 JSONL，
扫描 tail 即可人肉或后续渠道消费，渠道实现后只读同一文件。

为什么是 JSONL 追加而不是每事件一个文件：告警是运维流水，不是研究产物，
不需要 digest 身份；逐行追加天然保持时间序，且 sensor 进程崩溃不会写坏既有行。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class RunFailureAlert:
    """单次 Dagster run 失败的告警记录。字段只取诊断必需项，不复制整个事件。"""

    recorded_at: str
    dagster_run_id: str
    job_name: str
    run_status: str
    failure_message: str
    step_key: str | None
    schedule_name: str | None

    def to_jsonl(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False) + "\n"


def append_failure_alert(alert: RunFailureAlert, path: Path) -> None:
    """追加一行告警。目录不存在则创建；写坏一行不影响既有行，故不加锁。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(alert.to_jsonl())


def read_failure_alerts(path: Path, *, since: datetime) -> list[RunFailureAlert]:
    """读取 ``since`` 之后记录的告警；文件不存在等于没有告警。"""
    if not path.exists():
        return []
    alerts: list[RunFailureAlert] = []
    with path.open(encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            raw = json.loads(line)
            recorded = datetime.fromisoformat(raw["recorded_at"])
            if recorded >= since:
                alerts.append(RunFailureAlert(**raw))
    return alerts


def build_daily_summary(alerts: list[RunFailureAlert], *, day: str) -> dict[str, object]:
    """按 job 分组的每日汇总。``day`` 是汇总所属自然日（本地时区口径由调用方决定）。"""
    by_job: dict[str, list[dict[str, str]]] = {}
    for alert in alerts:
        by_job.setdefault(alert.job_name, []).append(
            {
                "dagster_run_id": alert.dagster_run_id,
                "failure_message": alert.failure_message,
                "recorded_at": alert.recorded_at,
            }
        )
    return {
        "day": day,
        "generated_at": datetime.now(UTC).isoformat(),
        "failure_count": len(alerts),
        "jobs": dict(sorted(by_job.items())),
    }


def write_daily_summary(summary: dict[str, object], path: Path) -> None:
    """每日汇总一天一份。同日重跑覆盖是预期行为：汇总可重算，事实在 JSONL 里。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


__all__ = [
    "RunFailureAlert",
    "append_failure_alert",
    "build_daily_summary",
    "read_failure_alerts",
    "write_daily_summary",
]
