"""run 失败告警 sensor：落盘内容、step 错误摘要、监控集合与调度定义不漂移。

不启动 dagster 实例，不连数据库；用假 context 直接调 record_run_failure。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from orchestration.definitions import defs
from orchestration.sensors.run_failure import (
    MONITORED_JOB_NAMES,
    record_run_failure,
    run_failure_alert,
)

from quantagent.platform.alerts import read_failure_alerts

if TYPE_CHECKING:
    from pathlib import Path

_EPOCH = datetime.min.replace(tzinfo=UTC)


@dataclass
class _FakeRun:
    run_id: str
    job_name: str
    tags: dict[str, str]

    @property
    def status(self) -> object:
        class _Status:
            value = "FAILURE"

        return _Status()


class _FakeError:
    def __init__(self, message: str) -> None:
        self.message = message


class _FakeStepFailureData:
    def __init__(self, message: str) -> None:
        self.error = _FakeError(message)


class _FakeStepEvent:
    def __init__(self, step_key: str, message: str) -> None:
        self.step_key = step_key
        self.step_failure_data = _FakeStepFailureData(message)


class _FakeFailureEvent:
    def __init__(self, message: str | None) -> None:
        self.message = message


class _FakeContext:
    """鸭子类型替身：record_run_failure 只用这四个成员。"""

    def __init__(
        self,
        *,
        job_name: str = "jydb_daily",
        step_events: list[_FakeStepEvent] | None = None,
        run_message: str | None = "run failed",
    ) -> None:
        self.dagster_run = _FakeRun(
            run_id="run-123",
            job_name=job_name,
            tags={"dagster/schedule_name": "jydb_daily_night"},
        )
        self._step_events = step_events or []
        self.failure_event = _FakeFailureEvent(run_message)

    def get_step_failure_events(self) -> list[_FakeStepEvent]:
        return self._step_events


@pytest.mark.unit
def test_step_failure_message_and_key_are_recorded(tmp_path: Path) -> None:
    path = tmp_path / "alerts.jsonl"
    context = _FakeContext(
        step_events=[_FakeStepEvent("src_jydb_qt_osindexquote", "IngestStalledError: 超过 600 秒没有新页\nstack")]
    )
    record_run_failure(context, path)  # type: ignore[arg-type]
    alerts = read_failure_alerts(path, since=_EPOCH)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.job_name == "jydb_daily"
    assert alert.dagster_run_id == "run-123"
    assert alert.step_key == "src_jydb_qt_osindexquote"
    # 只取首行，不带 traceback
    assert alert.failure_message == "IngestStalledError: 超过 600 秒没有新页"
    assert alert.schedule_name == "jydb_daily_night"


@pytest.mark.unit
def test_run_level_failure_without_step_falls_back_to_run_message(tmp_path: Path) -> None:
    path = tmp_path / "alerts.jsonl"
    record_run_failure(_FakeContext(run_message="启动执行进程失败"), path)  # type: ignore[arg-type]
    alerts = read_failure_alerts(path, since=_EPOCH)
    assert len(alerts) == 1
    assert alerts[0].failure_message == "启动执行进程失败"
    assert alerts[0].step_key is None


@pytest.mark.unit
def test_monitored_jobs_cover_all_local_scheduled_jobs() -> None:
    """每个被调度的作业都必须被监控：新加日更调度不加监控会在本测试暴露。

    单向覆盖而不是相等——监控集合可以提前包含即将上线的作业（如 suntime_daily），
    但调度里出现的作业绝不允许漏监。漏监才会重演 11-25 jydb 无人发现的事故。
    """
    # UnresolvedPartitionedAssetScheduleDefinition 没有 job_name；本项目调度全部直接挂 job。
    scheduled_jobs = {
        schedule.job_name
        for schedule in defs.schedules or []
        if hasattr(schedule, "job_name")
    }
    unmonitored = scheduled_jobs - set(MONITORED_JOB_NAMES)
    assert not unmonitored, f"调度作业未被失败告警监控: {sorted(unmonitored)}"


@pytest.mark.unit
def test_sensor_is_registered_and_running_by_default() -> None:
    names = [s.name for s in defs.sensors or []]
    assert "run_failure_alert" in names
    sensor = next(s for s in defs.sensors or [] if s.name == "run_failure_alert")
    assert sensor.default_status.value == "RUNNING"
    assert run_failure_alert.name == "run_failure_alert"
