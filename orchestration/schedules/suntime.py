"""朝阳永续日更调度。每天 01:10（上海）触发；同一作业未结束时跳过。

旧仓一天跑三次（22:00、02:00、04:30）。新仓一天一次，避开这三个时点，也避开
Wind 的 16:30、06:00 与聚源的 03:30。一致预期按自然日更新，不依赖交易日历。
只在能连源库、且没有其他机器同时启用本调度的机器上运行。
"""

from zoneinfo import ZoneInfo

from dagster import (
    DagsterRunStatus,
    DefaultScheduleStatus,
    RunRequest,
    RunsFilter,
    ScheduleDefinition,
    ScheduleEvaluationContext,
    SkipReason,
)

from orchestration.assets.suntime import (
    src_suntime_con_forecast_idx,
    src_suntime_con_forecast_roll_idx,
    src_suntime_con_forecast_roll_stk,
    src_suntime_con_forecast_stk,
    src_suntime_fin_income_gen,
    src_suntime_fin_performance_express,
    src_suntime_fin_performance_forecast,
    src_suntime_rpt_earnings_adjust,
)
from orchestration.jobs.suntime import suntime_daily

_TZ = "Asia/Shanghai"
_SCHEDULE_NAME = "suntime_daily_night"
_ACTIVE_STATUSES = [
    DagsterRunStatus.QUEUED,
    DagsterRunStatus.NOT_STARTED,
    DagsterRunStatus.STARTING,
    DagsterRunStatus.STARTED,
]
_ASSETS = (
    src_suntime_con_forecast_roll_idx,
    src_suntime_con_forecast_idx,
    src_suntime_rpt_earnings_adjust,
    src_suntime_fin_performance_forecast,
    src_suntime_fin_performance_express,
    src_suntime_fin_income_gen,
    src_suntime_con_forecast_roll_stk,
    src_suntime_con_forecast_stk,
)


def _evaluate(context: ScheduleEvaluationContext) -> RunRequest | SkipReason:
    if context.scheduled_execution_time is None:
        raise ValueError(f"{_SCHEDULE_NAME} 缺少 scheduled_execution_time")
    active = context.instance.get_runs(
        filters=RunsFilter(job_name=suntime_daily.name, statuses=_ACTIVE_STATUSES),
        limit=1,
    )
    if active:
        return SkipReason(f"{suntime_daily.name} 上一轮尚未结束，本次跳过")
    day = context.scheduled_execution_time.astimezone(ZoneInfo(_TZ)).date().isoformat()
    return RunRequest(
        run_key=f"{_SCHEDULE_NAME}:{day}",
        run_config={
            "ops": {
                item.op.name: {"config": {"write_db": True, "page_size": 1000}} for item in _ASSETS
            }
        },
    )


suntime_daily_night = ScheduleDefinition(
    name=_SCHEDULE_NAME,
    cron_schedule="10 1 * * *",
    job=suntime_daily,
    execution_timezone=_TZ,
    execution_fn=_evaluate,
    default_status=DefaultScheduleStatus.RUNNING,
)
