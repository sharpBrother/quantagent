from datetime import UTC, datetime

from dagster import DagsterInstance, DefaultScheduleStatus, build_schedule_context
from orchestration.schedules.minprice import minprice_first, minprice_retry


def test_daily_schedules_are_stopped_until_live_validation(monkeypatch, tmp_path):
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
    assert minprice_first.default_status == DefaultScheduleStatus.STOPPED
    assert minprice_retry.default_status == DefaultScheduleStatus.STOPPED
    assert (
        first.run_requests[0].run_config["ops"]["src_eastmoney_minute"]["config"]["final_attempt"]
        is False
    )
    assert (
        retry.run_requests[0].run_config["ops"]["src_eastmoney_minute"]["config"]["final_attempt"]
        is True
    )
