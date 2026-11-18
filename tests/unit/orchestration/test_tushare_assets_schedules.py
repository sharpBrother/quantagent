"""Tushare shibor 资产与日更调度：配置透传、起点来源、交易日跳过、并发保护。假源，不连接数据库。"""

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
from orchestration.assets import tushare as tushare_assets
from orchestration.assets.tushare import src_tushare_shibor
from orchestration.assets.wind import _pit_grade
from orchestration.jobs.tushare import tushare_daily
from orchestration.schedules import tushare as tushare_schedules
from orchestration.schedules.tushare import tushare_daily_evening

from quantagent.ingest.jobs.tushare_shibor import TushareShiborIngestResult
from quantagent.lake.materialize.trade_calendar import materialize_trade_calendar
from quantagent.platform.config import Settings
from quantagent.platform.storage.paths import VarPaths

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch
    from dagster._core.definitions.schedule_definition import ScheduleExecutionData

SRC_ROWS = (
    {"exchange": "SSE", "cal_date": "20260105", "is_open": 1, "pretrade_date": "20260104"},
    {"exchange": "SSE", "cal_date": "20260101", "is_open": 0, "pretrade_date": None},
)


def _result(*, written: bool) -> TushareShiborIngestResult:
    return TushareShiborIngestResult(
        dataset="src.tushare.shibor",
        written=written,
        segments=1,
        row_count=8,
        inserted=8,
        replaced=0,
        skipped=0,
        metadata_skipped=0,
        dml_count=2,
        empty_segments=(),
        batch_ids=(1,),
        payload_digest="a" * 64,
        output_digest="b" * 64,
    )


@pytest.mark.unit
def test_asset_is_a_grade_pit_source_and_defaults_to_dry_run() -> None:
    assert src_tushare_shibor.key.path[-1] == "src_tushare_shibor"
    metadata = src_tushare_shibor.metadata_by_key[src_tushare_shibor.key]
    assert metadata["pit_grade"] == "A"
    assert metadata["pit_grade"] == _pit_grade("src.tushare.shibor")
    assert tushare_assets.TushareShiborRunConfig(as_of="2024-12-01").write_db is False


@pytest.mark.unit
def test_asset_takes_start_from_batch_watermark_and_passes_config(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    settings = Settings(_env_file=None, var_root=tmp_path / "var")
    calls: dict[str, object] = {}

    def _start(*, settings: Settings, end_date: str) -> str:
        calls["resolve"] = end_date
        return "20241031"

    def _ingest(**kwargs: object) -> TushareShiborIngestResult:
        calls["ingest"] = kwargs
        return _result(written=bool(kwargs["write_db"]))

    monkeypatch.setattr("quantagent.platform.config.get_settings", lambda: settings)
    monkeypatch.setattr("quantagent.ingest.jobs.tushare_shibor.resolve_daily_start", _start)
    monkeypatch.setattr("quantagent.ingest.jobs.tushare_shibor.ingest_tushare_shibor", _ingest)

    result = materialize(
        [src_tushare_shibor],
        run_config={"ops": {"src_tushare_shibor": {"config": {"as_of": "2024-12-01"}}}},
    )
    assert result.success
    assert calls["resolve"] == "20241201"
    ingest_kwargs = calls["ingest"]
    assert isinstance(ingest_kwargs, dict)
    assert ingest_kwargs["start_date"] == "20241031"
    assert ingest_kwargs["end_date"] == "20241201"
    assert ingest_kwargs["write_db"] is False


@pytest.mark.unit
def test_daily_job_contains_only_the_shibor_asset() -> None:
    assert tushare_daily.name == "tushare_daily"
    resolved = Definitions(assets=[src_tushare_shibor], jobs=[tushare_daily]).get_job_def(
        "tushare_daily"
    )
    assert {key.path[-1] for key in resolved.asset_layer.executable_asset_keys} == {
        "src_tushare_shibor"
    }


@pytest.mark.unit
def test_daily_schedule_is_evening_shanghai_and_running_by_default() -> None:
    assert isinstance(tushare_daily_evening, ScheduleDefinition)
    assert tushare_daily_evening.cron_schedule == "0 19 * * *"
    assert tushare_daily_evening.execution_timezone == "Asia/Shanghai"
    assert tushare_daily_evening.default_status == DefaultScheduleStatus.RUNNING


@pytest.fixture
def calendar_env(tmp_path: Path, monkeypatch: MonkeyPatch) -> Settings:
    settings = Settings(_env_file=None, var_root=tmp_path / "var")
    root = tmp_path / "var"
    paths = VarPaths(
        root=root,
        lake=root / "lake",
        logs=root / "logs",
        runs=root / "logs" / "runs",
        cache=root / "cache",
    )
    materialize_trade_calendar(
        settings=settings,
        paths=paths,
        as_of=datetime(2026, 1, 1, tzinfo=UTC).date(),
        src_rows=SRC_ROWS,
    )
    monkeypatch.setattr(tushare_schedules, "get_settings", lambda: settings)
    monkeypatch.setattr(
        tushare_schedules,
        "resolve_var_paths",
        lambda _settings, *, repo_root: paths,
    )
    return settings


@pytest.fixture
def instance(tmp_path: Path) -> DagsterInstance:
    home = tmp_path / "dagster"
    home.mkdir()
    return DagsterInstance.local_temp(str(home))


def _tick(instance: DagsterInstance, scheduled: datetime) -> ScheduleExecutionData:
    context = build_schedule_context(instance=instance, scheduled_execution_time=scheduled)
    return tushare_daily_evening.evaluate_tick(context)


def _requests(tick: ScheduleExecutionData) -> list[RunRequest]:
    return list(tick.run_requests or [])


@pytest.mark.unit
def test_open_day_requests_run_with_end_date_and_write_flag(
    calendar_env: Settings, instance: DagsterInstance
) -> None:
    # 2026-01-05 19:00 上海 = 11:00 UTC。起点不由调度给出，由资产读 _batch 决定。
    tick = _tick(instance, datetime(2026, 1, 5, 11, 0, tzinfo=UTC))
    assert len(_requests(tick)) == 1
    request = _requests(tick)[0]
    assert request.run_key == "tushare_daily_evening:2026-01-05"
    assert request.run_config["ops"][src_tushare_shibor.op.name]["config"] == {
        "as_of": "2026-01-05",
        "write_db": True,
    }


@pytest.mark.unit
def test_closed_day_is_skipped(calendar_env: Settings, instance: DagsterInstance) -> None:
    tick = _tick(instance, datetime(2026, 1, 1, 11, 0, tzinfo=UTC))
    assert _requests(tick) == []
    assert isinstance(tick.skip_message, str)
    assert "非 SSE 交易日" in tick.skip_message


@pytest.mark.unit
def test_active_tushare_run_blocks_new_tick(
    calendar_env: Settings, instance: DagsterInstance
) -> None:
    create_run_for_test(
        instance,
        job_name="tushare_daily",
        status=DagsterRunStatus.STARTED,
    )
    tick = _tick(instance, datetime(2026, 1, 5, 11, 0, tzinfo=UTC))
    assert _requests(tick) == []
    assert isinstance(tick.skip_message, str)
    assert "尚未结束" in tick.skip_message


@pytest.mark.unit
def test_wind_run_does_not_block_tushare_tick(
    calendar_env: Settings, instance: DagsterInstance
) -> None:
    create_run_for_test(
        instance,
        job_name="wind_source_daily",
        status=DagsterRunStatus.STARTED,
    )
    tick = _tick(instance, datetime(2026, 1, 5, 11, 0, tzinfo=UTC))
    assert len(_requests(tick)) == 1
