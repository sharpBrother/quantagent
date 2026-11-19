"""GPR 日频资产、作业与调度：配置透传、默认干跑、自然日触发、不查交易日历、并发保护。假源，不联网。"""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime
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
from orchestration.jobs.macro import macro_daily
from orchestration.schedules import macro as macro_schedules
from orchestration.schedules.macro import macro_daily_morning

from quantagent.ingest.jobs.macro_gpr import MacroGprIngestResult
from quantagent.platform.config import Settings

if TYPE_CHECKING:
    from pathlib import Path

    from dagster._core.definitions.schedule_definition import ScheduleExecutionData
    from pytest import MonkeyPatch

_DATASET = "src.macro.gpr_daily"


def _result(*, written: bool) -> MacroGprIngestResult:
    return MacroGprIngestResult(
        dataset=_DATASET,
        written=written,
        unchanged=False,
        file_sha256="a" * 64,
        file_vintage=date(2026, 11, 16),
        observation_min=date(1985, 1, 1),
        observation_max=date(2026, 11, 16),
        row_count=91770,
        series_rows=(("GPRD", 15295),),
        inserted=91770 if written else 0,
        replaced=0,
        skipped=0,
        metadata_skipped=0,
        unchanged_points=0,
        dml_count=2 if written else 0,
        batch_id=1 if written else None,
        payload_digest="b" * 64,
        output_digest="c" * 64,
    )


@pytest.mark.unit
def test_asset_is_c_grade_pit_source_and_defaults_to_dry_run() -> None:
    assert src_macro_gpr_daily.key.path[-1] == "src_macro_gpr_daily"
    metadata = src_macro_gpr_daily.metadata_by_key[src_macro_gpr_daily.key]
    # GPR 的 file_vintage 是由数据推出的近似版本，契约等级为 C。
    assert metadata["pit_grade"] == "C"
    assert metadata["pit_grade"] == _pit_grade(_DATASET)
    assert macro_assets.MacroGprRunConfig().write_db is False


@pytest.mark.unit
def test_asset_passes_write_flag_to_the_job_and_reports_metadata(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    settings = Settings(_env_file=None, var_root=tmp_path / "var")
    calls: dict[str, object] = {}

    def _ingest(**kwargs: object) -> MacroGprIngestResult:
        calls.update(kwargs)
        return _result(written=bool(kwargs["write_db"]))

    monkeypatch.setattr("quantagent.platform.config.get_settings", lambda: settings)
    monkeypatch.setattr("quantagent.ingest.jobs.macro_gpr.ingest_macro_gpr", _ingest)
    result = materialize(
        [src_macro_gpr_daily],
        run_config={"ops": {"src_macro_gpr_daily": {"config": {"write_db": True}}}},
    )
    assert result.success
    assert calls["write_db"] is True
    assert "as_of" not in calls
    assert "start_date" not in calls


@pytest.mark.unit
def test_default_run_is_dry_run(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    settings = Settings(_env_file=None, var_root=tmp_path / "var")
    calls: dict[str, object] = {}

    def _ingest(**kwargs: object) -> MacroGprIngestResult:
        calls.update(kwargs)
        return _result(written=False)

    monkeypatch.setattr("quantagent.platform.config.get_settings", lambda: settings)
    monkeypatch.setattr("quantagent.ingest.jobs.macro_gpr.ingest_macro_gpr", _ingest)
    result = materialize([src_macro_gpr_daily])
    assert result.success
    assert calls["write_db"] is False


@pytest.mark.unit
def test_macro_daily_job_includes_the_gpr_asset() -> None:
    # macro_daily 与 FRED 共用一个作业，两者都要在 Definitions 里才能解析。
    assert macro_daily.name == "macro_daily"
    resolved = Definitions(
        assets=[src_macro_gpr_daily, src_macro_fred_observation_vintage],
        jobs=[macro_daily],
    ).get_job_def("macro_daily")
    assert "src_macro_gpr_daily" in {
        key.path[-1] for key in resolved.asset_layer.executable_asset_keys
    }


@pytest.mark.unit
def test_schedule_is_morning_shanghai_and_running_by_default() -> None:
    assert isinstance(macro_daily_morning, ScheduleDefinition)
    assert macro_daily_morning.name == "macro_daily_morning"
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
def test_schedule_runs_on_a_closed_exchange_day(instance: DagsterInstance) -> None:
    # 公开源按自然日跑。2026-01-01 是元旦，上交所休市，调度仍要发出请求。
    # 2026-01-01 00:00 UTC = 08:00 上海。
    tick = _tick(instance, datetime(2026, 1, 1, 0, 0, tzinfo=UTC))
    requests = list(tick.run_requests or [])
    assert len(requests) == 1
    request: RunRequest = requests[0]
    assert request.run_key == "macro_daily_morning:2026-01-01"
    assert request.run_config is not None
    ops = request.run_config["ops"]
    assert ops[src_macro_gpr_daily.op.name]["config"] == {"write_db": True}


@pytest.mark.unit
def test_schedule_source_never_reads_the_trade_calendar() -> None:
    source = inspect.getsource(macro_schedules).lower()
    assert "calendar" not in source


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
