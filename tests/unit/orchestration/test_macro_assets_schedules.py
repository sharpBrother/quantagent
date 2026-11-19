"""宏观日更资产、作业与调度：配置透传、默认干跑、自然日触发、不查交易日历、并发保护。假源，不联网。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from dagster import (
    DagsterInstance,
    DagsterRunStatus,
    DefaultScheduleStatus,
    Definitions,
    RunRequest,
    ScheduleDefinition,
    build_schedule_context,
    materialize,
)
from dagster._core.test_utils import create_run_for_test
from orchestration.assets import macro as macro_assets
from orchestration.assets.macro import src_macro_fred_observation_vintage, src_macro_gpr_daily
from orchestration.assets.wind import _pit_grade
from orchestration.definitions import defs, schedules_for_profile
from orchestration.jobs.macro import macro_daily
from orchestration.schedules.macro import macro_daily_morning

from quantagent.platform.config import Settings

if TYPE_CHECKING:
    from pathlib import Path

    from dagster._core.definitions.schedule_definition import ScheduleExecutionData
    from pytest import MonkeyPatch


class _FakeResult:
    """替代 ``MacroFredIngestResult``，只提供资产元数据用到的字段。"""

    series: tuple[object, ...] = ()
    row_count = 0
    inserted = 0
    replaced = 0
    skipped = 0
    metadata_skipped = 0
    dml_count = 0


@pytest.mark.unit
def test_asset_is_a_grade_pit_source_and_defaults_to_dry_run() -> None:
    assert src_macro_fred_observation_vintage.key.path[-1] == "src_macro_fred_observation_vintage"
    metadata = src_macro_fred_observation_vintage.metadata_by_key[
        src_macro_fred_observation_vintage.key
    ]
    assert metadata["pit_grade"] == "A"
    assert metadata["pit_grade"] == _pit_grade("src.macro.fred_observation_vintage")
    assert macro_assets.MacroFredRunConfig().write_db is False


@pytest.mark.unit
def test_asset_passes_write_flag_and_reports_no_start_or_as_of(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    settings = Settings(_env_file=None, var_root=tmp_path / "var")
    calls: dict[str, object] = {}

    def _ingest(**kwargs: object) -> _FakeResult:
        calls.update(kwargs)
        return _FakeResult()

    monkeypatch.setattr("quantagent.platform.config.get_settings", lambda: settings)
    monkeypatch.setattr("quantagent.ingest.jobs.macro_fred.ingest_macro_fred", _ingest)
    result = materialize(
        [src_macro_fred_observation_vintage],
        run_config={"ops": {"src_macro_fred_observation_vintage": {"config": {}}}},
    )
    assert result.success
    assert calls["write_db"] is False
    assert "start_date" not in calls
    assert "as_of" not in calls


@pytest.mark.unit
def test_macro_daily_job_contains_the_fred_asset() -> None:
    assert macro_daily.name == "macro_daily"
    # macro_daily 同时选中 GPR 与 FRED 两个资产，两者都要在 Definitions 里，作业才能解析。
    resolved = Definitions(
        assets=[src_macro_fred_observation_vintage, src_macro_gpr_daily], jobs=[macro_daily]
    ).get_job_def("macro_daily")
    assert {key.path[-1] for key in resolved.asset_layer.executable_asset_keys} == {
        "src_macro_fred_observation_vintage",
        "src_macro_gpr_daily",
    }


@pytest.mark.unit
def test_definitions_register_macro_job_and_schedule() -> None:
    assert defs.get_job_def("macro_daily").name == "macro_daily"
    # 调度按 profile 注册（Mac 才有 macro 调度），这里直接取 local 的调度，测试不依赖本机 profile。
    schedule = next(s for s in schedules_for_profile("local") if s.name == "macro_daily_morning")
    assert schedule.cron_schedule == "0 8 * * *"


@pytest.mark.unit
def test_daily_schedule_is_morning_shanghai_and_running_by_default() -> None:
    assert isinstance(macro_daily_morning, ScheduleDefinition)
    assert macro_daily_morning.cron_schedule == "0 8 * * *"
    assert macro_daily_morning.execution_timezone == "Asia/Shanghai"
    assert macro_daily_morning.default_status == DefaultScheduleStatus.RUNNING


@pytest.fixture
def instance(tmp_path: Path) -> DagsterInstance:
    home = tmp_path / "dagster"
    home.mkdir()
    return DagsterInstance.local_temp(str(home))


def _tick(instance: DagsterInstance, scheduled: datetime) -> ScheduleExecutionData:
    context = build_schedule_context(instance=instance, scheduled_execution_time=scheduled)
    return macro_daily_morning.evaluate_tick(context)


@pytest.mark.unit
def test_schedule_requests_every_natural_day_without_calendar_check(
    instance: DagsterInstance,
) -> None:
    # 2026-01-01 是元旦，上交所休市。宏观日更仍要跑，因为 FRED 的版本与交易日无关。
    # 2026-01-01 00:00 UTC = 08:00 上海。
    tick = _tick(instance, datetime(2026, 1, 1, 0, 0, tzinfo=UTC))
    requests = list(tick.run_requests or [])
    assert len(requests) == 1
    request: RunRequest = requests[0]
    assert request.run_key == "macro_daily_morning:2026-01-01"
    assert request.run_config is not None
    ops = request.run_config["ops"]
    assert ops[src_macro_fred_observation_vintage.op.name]["config"] == {"write_db": True}


@pytest.mark.unit
def test_active_macro_run_blocks_new_tick(instance: DagsterInstance) -> None:
    create_run_for_test(instance, job_name="macro_daily", status=DagsterRunStatus.STARTED)
    tick = _tick(instance, datetime(2026, 1, 1, 0, 0, tzinfo=UTC))
    assert list(tick.run_requests or []) == []
    assert isinstance(tick.skip_message, str)
    assert "尚未结束" in tick.skip_message


@pytest.mark.unit
def test_tushare_run_does_not_block_macro_tick(instance: DagsterInstance) -> None:
    create_run_for_test(instance, job_name="tushare_daily", status=DagsterRunStatus.STARTED)
    tick = _tick(instance, datetime(2026, 1, 1, 0, 0, tzinfo=UTC))
    assert len(list(tick.run_requests or [])) == 1
