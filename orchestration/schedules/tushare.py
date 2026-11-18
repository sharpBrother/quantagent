"""Tushare 日更调度。每天 19:00（上海）触发，按 SSE 交易日历跳过非交易日。

这个调度只在 Mac（``QUANTAGENT_PROFILE=local``）上跑。公司电脑的 profile 是 ``office``，
写入会被拒绝，所以不要在公司电脑上启用它。

判断写法与 ``orchestration/schedules/wind.py`` 一致，包括"上一轮未结束则跳过"。
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

from orchestration.assets.tushare import src_tushare_shibor, src_tushare_us_treasury_yield
from orchestration.jobs.tushare import tushare_daily
from quantagent.platform.config import get_settings
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

_TZ = "Asia/Shanghai"
_EXCHANGE = "SSE"
_SCHEDULE_NAME = "tushare_daily_evening"
_ACTIVE_STATUSES = [
    DagsterRunStatus.QUEUED,
    DagsterRunStatus.NOT_STARTED,
    DagsterRunStatus.STARTING,
    DagsterRunStatus.STARTED,
]


def _has_active_run(context: ScheduleEvaluationContext) -> bool:
    runs = context.instance.get_runs(
        filters=RunsFilter(job_name=tushare_daily.name, statuses=_ACTIVE_STATUSES),
        limit=1,
    )
    return bool(runs)


def _evaluate(context: ScheduleEvaluationContext) -> RunRequest | SkipReason:
    if context.scheduled_execution_time is None:
        raise ValueError(f"{_SCHEDULE_NAME} 缺少 scheduled_execution_time，拒绝猜测交易日")
    if _has_active_run(context):
        return SkipReason(f"{tushare_daily.name} 上一轮尚未结束，本次跳过")
    today = context.scheduled_execution_time.astimezone(ZoneInfo(_TZ)).date()
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    # 日历读取出错不吞掉：让 tick 报错，不在日历不可信时默认跑或默认跳过。
    from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
    from quantagent.domain.calendar.queries import CalendarQueries

    calendar = CalendarQueries(LakeCalendarRepository(paths.lake / "std" / "trade_calendar"))
    if not calendar.is_open(exchange=_EXCHANGE, cal_dt=today, as_of=today):
        return SkipReason(f"{today.isoformat()} 非 {_EXCHANGE} 交易日")
    return RunRequest(
        run_key=f"{_SCHEDULE_NAME}:{today.isoformat()}",
        run_config={
            "ops": {
                src_tushare_shibor.op.name: {
                    "config": {
                        "as_of": today.isoformat(),
                        # 全自动写入。日更起点由 src_tushare._batch 决定，不由调度给出。
                        "write_db": True,
                    }
                },
                src_tushare_us_treasury_yield.op.name: {
                    "config": {
                        "as_of": today.isoformat(),
                        "write_db": True,
                    }
                },
            }
        },
    )


tushare_daily_evening = ScheduleDefinition(
    name=_SCHEDULE_NAME,
    cron_schedule="0 19 * * *",
    job=tushare_daily,
    execution_timezone=_TZ,
    execution_fn=_evaluate,
    # 全自动：daemon 一启动调度即生效，不需要在 UI 里手动打开。
    default_status=DefaultScheduleStatus.RUNNING,
)
