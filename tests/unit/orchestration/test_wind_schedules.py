"""Wind 日更调度的评估函数：交易日判断、并发保护、run_config 内容。日历用临时 Parquet，不连接数据库。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from dagster import (
    DagsterInstance,
    DagsterRunStatus,
    RunRequest,
    ScheduleDefinition,
    build_schedule_context,
)
from dagster._core.test_utils import create_run_for_test
from orchestration.assets.wind import WIND_SOURCE_ASSETS, std_trade_calendar
from orchestration.schedules import wind as wind_schedules
from orchestration.schedules.wind import wind_source_daily_close, wind_source_daily_morning

from quantagent.domain.errors import EmptyDomainError
from quantagent.lake.materialize.trade_calendar import (
    DAILY_HORIZON_DAYS,
    materialize_trade_calendar,
)
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
    monkeypatch.setattr(wind_schedules, "get_settings", lambda: settings)
    monkeypatch.setattr(
        wind_schedules,
        "resolve_var_paths",
        lambda _settings, *, repo_root: paths,
    )
    return settings


def _requests(tick: ScheduleExecutionData) -> list[RunRequest]:
    return list(tick.run_requests or [])


@pytest.fixture
def instance(tmp_path: Path) -> DagsterInstance:
    # evaluate_tick 只把持久化实例的引用交给上下文；ephemeral 实例会被忽略，所以这里用临时本地实例。
    home = tmp_path / "dagster"
    home.mkdir()
    return DagsterInstance.local_temp(str(home))


def _tick(
    schedule: ScheduleDefinition,
    scheduled: datetime,
    instance: DagsterInstance,
) -> ScheduleExecutionData:
    context = build_schedule_context(
        instance=instance,
        scheduled_execution_time=scheduled,
    )
    return schedule.evaluate_tick(context)


@pytest.mark.unit
def test_open_day_returns_run_request_with_pinned_config(
    calendar_env: Settings, instance: DagsterInstance
) -> None:
    # 2026-01-05 16:30 上海 = 08:30 UTC；收盘批次。
    tick = _tick(wind_source_daily_close, datetime(2026, 1, 5, 8, 30, tzinfo=UTC), instance)
    assert len(_requests(tick)) == 1
    request = _requests(tick)[0]
    assert request.run_key == "wind_source_daily_close:2026-01-05"
    ops = request.run_config["ops"]
    for asset in WIND_SOURCE_ASSETS:
        cfg = ops[asset.op.name]["config"]
        assert cfg == {
            "as_of": "2026-01-05",
            # 负责人裁定的全自动写入，见 schedules/wind.py 中的注释。
            "write_db": True,
            "max_pages": None,
            "page_size": 10000,
        }
    calendar_cfg = ops[std_trade_calendar.op.name]["config"]
    assert calendar_cfg == {
        "as_of": "2026-01-05",
        "rebuild": False,
        "append_only": True,
        "horizon_days": 7,
    }
    assert calendar_cfg["append_only"] is True
    assert calendar_cfg["horizon_days"] == DAILY_HORIZON_DAYS


@pytest.mark.unit
def test_morning_schedule_uses_its_own_run_key(
    calendar_env: Settings, instance: DagsterInstance
) -> None:
    # 06:00 上海 = 前一日 22:00 UTC，验证按上海日期取日。
    tick = _tick(wind_source_daily_morning, datetime(2026, 1, 4, 22, 0, tzinfo=UTC), instance)
    assert len(_requests(tick)) == 1
    assert _requests(tick)[0].run_key == "wind_source_daily_morning:2026-01-05"


@pytest.mark.unit
def test_closed_day_is_skipped(calendar_env: Settings, instance: DagsterInstance) -> None:
    tick = _tick(wind_source_daily_close, datetime(2026, 1, 1, 8, 30, tzinfo=UTC), instance)
    assert _requests(tick) == []
    assert tick.skip_message is not None
    assert "非 SSE 交易日" in tick.skip_message


@pytest.mark.unit
def test_date_missing_from_calendar_raises_instead_of_guessing(
    calendar_env: Settings, instance: DagsterInstance
) -> None:
    # 2026-01-02 不在日历快照里，应报错而不是默认跑或默认跳过。
    with pytest.raises(EmptyDomainError, match="日历域为空"):
        _tick(wind_source_daily_close, datetime(2026, 1, 2, 8, 30, tzinfo=UTC), instance)


@pytest.mark.unit
def test_active_run_blocks_new_tick(calendar_env: Settings, instance: DagsterInstance) -> None:
    create_run_for_test(
        instance,
        job_name="wind_source_daily",
        status=DagsterRunStatus.STARTED,
    )
    tick = _tick(wind_source_daily_morning, datetime(2026, 1, 5, 22, 0, tzinfo=UTC), instance)
    assert _requests(tick) == []
    assert tick.skip_message is not None
    assert "尚未结束" in tick.skip_message


@pytest.mark.unit
def test_finished_run_does_not_block(calendar_env: Settings, instance: DagsterInstance) -> None:
    create_run_for_test(
        instance,
        job_name="wind_source_daily",
        status=DagsterRunStatus.SUCCESS,
    )
    tick = _tick(wind_source_daily_close, datetime(2026, 1, 5, 8, 30, tzinfo=UTC), instance)
    assert len(_requests(tick)) == 1
