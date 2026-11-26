from datetime import UTC, datetime
from pathlib import Path

import pytest
from dagster import DagsterInstance, DefaultScheduleStatus, build_schedule_context
from orchestration.schedules.minprice import minprice_first, minprice_retry


def test_daily_mysql_schedules_have_safe_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "quantagent.domain.calendar.queries.CalendarQueries.is_open", lambda *a, **kw: True
    )
    instance = DagsterInstance.local_temp(str(tmp_path))
    first = minprice_first.evaluate_tick(
        build_schedule_context(
            instance=instance, scheduled_execution_time=datetime(2026, 11, 20, 8, tzinfo=UTC)
        )
    )
    retry = minprice_retry.evaluate_tick(
        build_schedule_context(
            instance=instance, scheduled_execution_time=datetime(2026, 11, 20, 9, tzinfo=UTC)
        )
    )
    assert first.run_requests is not None
    assert retry.run_requests is not None
    assert minprice_first.default_status == DefaultScheduleStatus.STOPPED
    assert minprice_retry.default_status == DefaultScheduleStatus.STOPPED
    assert (
        first.run_requests[0].run_config["ops"]["src_mysql_minute"]["config"]["final_attempt"]
        is False
    )
    assert (
        retry.run_requests[0].run_config["ops"]["src_mysql_minute"]["config"]["final_attempt"]
        is True
    )
