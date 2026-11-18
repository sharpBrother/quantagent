"""宏观公开源日更调度。每天 08:00（上海）触发，不做交易日判断。

公开源（GPR 等）不随 SSE 交易日更新，所以这里不查交易日历，也不因非交易日跳过。
判断写法与 ``orchestration/schedules/tushare.py`` 一致，包括"上一轮未结束则跳过"。
这个调度只在 Mac（``QUANTAGENT_PROFILE=local``）上跑，公司电脑不要启用它。
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

from orchestration.assets.macro import src_macro_fred_observation_vintage, src_macro_gpr_daily
from orchestration.jobs.macro import macro_daily

_TZ = "Asia/Shanghai"
_SCHEDULE_NAME = "macro_daily_morning"

_ACTIVE_STATUSES = [
    DagsterRunStatus.QUEUED,
    DagsterRunStatus.NOT_STARTED,
    DagsterRunStatus.STARTING,
    DagsterRunStatus.STARTED,
]


def _has_active_run(context: ScheduleEvaluationContext) -> bool:
    runs = context.instance.get_runs(
        filters=RunsFilter(job_name=macro_daily.name, statuses=_ACTIVE_STATUSES),
        limit=1,
    )
    return bool(runs)


def _evaluate(context: ScheduleEvaluationContext) -> RunRequest | SkipReason:
    if context.scheduled_execution_time is None:
        raise ValueError(f"{_SCHEDULE_NAME} 缺少 scheduled_execution_time，拒绝猜测日期")
    if _has_active_run(context):
        return SkipReason(f"{macro_daily.name} 上一轮尚未结束，本次跳过")
    today = context.scheduled_execution_time.astimezone(ZoneInfo(_TZ)).date()
    return RunRequest(
        run_key=f"{_SCHEDULE_NAME}:{today.isoformat()}",
        run_config={
            "ops": {
                src_macro_gpr_daily.op.name: {
                    "config": {
                        # 全自动写入。无更新由资产内的 file_sha256 比对决定，调度不判断。
                        "write_db": True,
                    }
                },
                src_macro_fred_observation_vintage.op.name: {
                    "config": {
                        # 全量拉取，不需要起点或 as_of。
                        "write_db": True,
                    }
                },
            }
        },
    )


macro_daily_morning = ScheduleDefinition(
    name=_SCHEDULE_NAME,
    cron_schedule="0 8 * * *",
    job=macro_daily,
    execution_timezone=_TZ,
    execution_fn=_evaluate,
    # 全自动：daemon 一启动调度即生效，不需要在 UI 里手动打开。
    default_status=DefaultScheduleStatus.RUNNING,
)
