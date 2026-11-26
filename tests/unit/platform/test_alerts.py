"""告警落盘与每日汇总：追加、按时间过滤、汇总分组、覆盖写。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from quantagent.platform.alerts import (
    RunFailureAlert,
    append_failure_alert,
    build_daily_summary,
    read_failure_alerts,
    write_daily_summary,
)

if TYPE_CHECKING:
    from pathlib import Path


def _alert(recorded_at: str, job: str = "jydb_daily", message: str = "boom") -> RunFailureAlert:
    return RunFailureAlert(
        recorded_at=recorded_at,
        dagster_run_id="run-1",
        job_name=job,
        run_status="FAILURE",
        failure_message=message,
        step_key=None,
        schedule_name=None,
    )


@pytest.mark.unit
def test_append_and_read_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "alerts" / "run_failures.jsonl"
    append_failure_alert(_alert("2026-11-25T09:00:00+00:00"), path)
    append_failure_alert(_alert("2026-11-25T23:30:00+00:00", job="wind_source_daily"), path)
    all_alerts = read_failure_alerts(path, since=datetime(2026, 1, 1, tzinfo=UTC))
    assert len(all_alerts) == 2
    assert all_alerts[1].job_name == "wind_source_daily"
    # since 之后的才返回
    late = read_failure_alerts(path, since=datetime(2026, 11, 25, 12, tzinfo=UTC))
    assert len(late) == 1
    assert late[0].recorded_at == "2026-11-25T23:30:00+00:00"


@pytest.mark.unit
def test_read_missing_file_returns_empty(tmp_path: Path) -> None:
    assert read_failure_alerts(tmp_path / "none.jsonl", since=datetime(2026, 1, 1, tzinfo=UTC)) == []


@pytest.mark.unit
def test_summary_groups_by_job_and_counts() -> None:
    alerts = [
        _alert("2026-11-25T01:00:00+00:00", job="jydb_daily"),
        _alert("2026-11-25T02:00:00+00:00", job="jydb_daily"),
        _alert("2026-11-25T03:00:00+00:00", job="suntime_daily"),
    ]
    summary = build_daily_summary(alerts, day="2026-11-25")
    assert summary["day"] == "2026-11-25"
    assert summary["failure_count"] == 3
    jobs = summary["jobs"]
    assert isinstance(jobs, dict)
    assert sorted(jobs) == ["jydb_daily", "suntime_daily"]
    assert len(jobs["jydb_daily"]) == 2
    assert len(jobs["suntime_daily"]) == 1


@pytest.mark.unit
def test_write_summary_overwrites_same_day(tmp_path: Path) -> None:
    dest = tmp_path / "summary" / "2026-11-25.json"
    write_daily_summary({"day": "2026-11-25", "failure_count": 0, "jobs": {}}, dest)
    write_daily_summary({"day": "2026-11-25", "failure_count": 2, "jobs": {}}, dest)
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["failure_count"] == 2
