"""日更因子与前瞻收益调度：只在 local 注册、时间正确、非交易日跳过、运行键按触发时刻区分。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from dagster import (
    DagsterInstance,
    DefaultScheduleStatus,
    RunRequest,
    ScheduleDefinition,
    build_schedule_context,
)
from orchestration.definitions import PROFILE_SCHEDULES, schedules_for_profile
from orchestration.jobs.daily_feature import DAILY_FEATURE_JOB_ASSETS

if TYPE_CHECKING:
    from pathlib import Path

from orchestration.schedules.daily_feature import (
    feature_daily_main_schedule,
    feature_forward_return_daily_schedule,
    feature_minute_daily_schedule,
    feature_umr_daily_schedule,
)

_NEW = {
    "feature_forward_return_daily",
    "feature_minute_daily",
    "feature_daily_main",
    "feature_umr_daily",
}


@pytest.mark.unit
def test_new_schedules_are_registered_for_local_only() -> None:
    local = {schedule.name for schedule in schedules_for_profile("local")}
    office = {schedule.name for schedule in schedules_for_profile("office")}
    assert local >= _NEW
    assert not (_NEW & office)
    assert {s.name for s in PROFILE_SCHEDULES["local"]} >= _NEW


@pytest.mark.unit
def test_cron_times_follow_the_agreed_slots() -> None:
    assert feature_forward_return_daily_schedule.cron_schedule == [
        "30 17 * * *",
        "0 0 * * *",
        "0 2 * * *",
    ]
    assert feature_minute_daily_schedule.cron_schedule == "30 19 * * *"
    assert feature_daily_main_schedule.cron_schedule == "10 4 * * *"
    assert feature_umr_daily_schedule.cron_schedule == "30 4 * * *"
    for schedule in (
        feature_forward_return_daily_schedule,
        feature_minute_daily_schedule,
        feature_daily_main_schedule,
        feature_umr_daily_schedule,
    ):
        assert schedule.execution_timezone == "Asia/Shanghai"
        assert schedule.default_status == DefaultScheduleStatus.RUNNING


def _tick(schedule: ScheduleDefinition, when: datetime, tmp_path: Path) -> Any:
    tmp_path.mkdir(parents=True, exist_ok=True)
    instance = DagsterInstance.local_temp(str(tmp_path))
    return schedule.evaluate_tick(
        build_schedule_context(instance=instance, scheduled_execution_time=when)
    )


@pytest.mark.unit
def test_trading_day_tick_requests_run_with_today_as_of_for_every_op(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "quantagent.domain.calendar.queries.CalendarQueries.is_open", lambda *a, **kw: True
    )
    # 2026-11-25 09:30 UTC 即上海 17:30。
    result = _tick(
        feature_forward_return_daily_schedule, datetime(2026, 11, 25, 9, 30, tzinfo=UTC), tmp_path
    )
    assert result.run_requests is not None
    request = result.run_requests[0]
    assert isinstance(request, RunRequest)
    ops = request.run_config["ops"]
    expected_ops = {a.op.name for a in DAILY_FEATURE_JOB_ASSETS["feature_forward_return_daily"]}
    assert set(ops) == expected_ops
    assert all(cfg["config"] == {"as_of": "2026-11-25"} for cfg in ops.values())


@pytest.mark.unit
def test_run_key_differs_between_the_three_forward_return_ticks_of_one_day(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "quantagent.domain.calendar.queries.CalendarQueries.is_open", lambda *a, **kw: True
    )
    # 上海 00:00 属于 11-25，与 17:30 同一天；运行键必须仍不同。
    evening = _tick(
        feature_forward_return_daily_schedule,
        datetime(2026, 11, 25, 9, 30, tzinfo=UTC),
        tmp_path / "a",
    )
    midnight = _tick(
        feature_forward_return_daily_schedule,
        datetime(2026, 11, 24, 16, 0, tzinfo=UTC),
        tmp_path / "b",
    )
    assert evening.run_requests[0].run_key != midnight.run_requests[0].run_key
    assert midnight.run_requests[0].run_config["ops"]
    any_op = next(iter(midnight.run_requests[0].run_config["ops"].values()))
    assert any_op["config"]["as_of"] == "2026-11-25"


@pytest.mark.unit
def test_non_trading_day_is_skipped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "quantagent.domain.calendar.queries.CalendarQueries.is_open", lambda *a, **kw: False
    )
    result = _tick(feature_umr_daily_schedule, datetime(2026, 11, 21, 20, 30, tzinfo=UTC), tmp_path)
    assert result.run_requests in (None, [])
    assert result.skip_message is not None
    assert "非 SSE 交易日" in result.skip_message
