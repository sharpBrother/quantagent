"""WGC 周更按上海时间触发，并阻止同时运行。"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from dagster import DefaultScheduleStatus, RunRequest, SkipReason
from orchestration.schedules.macro import _evaluate_wgc, macro_wgc_sunday


@pytest.mark.unit
def test_sunday_tick_writes_explicitly_and_prevents_overlap() -> None:
    assert macro_wgc_sunday.cron_schedule == "0 12 * * 0"
    assert macro_wgc_sunday.execution_timezone == "Asia/Shanghai"
    assert macro_wgc_sunday.default_status == DefaultScheduleStatus.RUNNING
    instance = MagicMock()
    instance.get_runs.return_value = []
    context = SimpleNamespace(
        instance=instance, scheduled_execution_time=datetime(2026, 11, 22, 4, tzinfo=UTC)
    )
    request = _evaluate_wgc(context)  # type: ignore[arg-type]
    assert isinstance(request, RunRequest)
    assert request.run_key == "macro_wgc_weekly:2026-11-22"
    assert request.run_config["ops"]["src_macro_wgc_gold_demand"]["config"]["write_db"] is True
    instance.get_runs.return_value = [object()]
    assert isinstance(_evaluate_wgc(context), SkipReason)  # type: ignore[arg-type]
