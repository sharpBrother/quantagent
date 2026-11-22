"""东财分钟行情 16:00 首次采集、17:00 补跑。"""

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

from orchestration.assets.minprice import src_eastmoney_minute
from orchestration.jobs.minprice import minprice_daily
from quantagent.platform.config import get_settings
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

_ACTIVE = [
    DagsterRunStatus.QUEUED,
    DagsterRunStatus.NOT_STARTED,
    DagsterRunStatus.STARTING,
    DagsterRunStatus.STARTED,
]


def _evaluate(context: ScheduleEvaluationContext, *, final: bool) -> RunRequest | SkipReason:
    if context.scheduled_execution_time is None:
        raise ValueError("分钟行情调度缺少执行时间")
    if context.instance.get_runs(
        filters=RunsFilter(job_name=minprice_daily.name, statuses=_ACTIVE), limit=1
    ):
        return SkipReason("上一轮分钟采集尚未结束")
    today = context.scheduled_execution_time.astimezone(ZoneInfo("Asia/Shanghai")).date()
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
    from quantagent.domain.calendar.queries import CalendarQueries

    cal = CalendarQueries(LakeCalendarRepository(paths.lake / "std" / "trade_calendar"))
    if not cal.is_open(exchange="SSE", cal_dt=today, as_of=today):
        return SkipReason(f"{today} 非交易日")
    return RunRequest(
        run_key=f"{today}:{int(final)}",
        run_config={
            "ops": {
                src_eastmoney_minute.op.name: {
                    "config": {
                        "as_of": str(today),
                        "write_db": True,
                        "final_attempt": final,
                    }
                }
            }
        },
    )


minprice_first = ScheduleDefinition(
    name="minprice_first",
    cron_schedule="0 16 * * *",
    job=minprice_daily,
    execution_timezone="Asia/Shanghai",
    execution_fn=lambda c: _evaluate(c, final=False),
    default_status=DefaultScheduleStatus.STOPPED,
)
minprice_retry = ScheduleDefinition(
    name="minprice_retry",
    cron_schedule="0 17 * * *",
    job=minprice_daily,
    execution_timezone="Asia/Shanghai",
    execution_fn=lambda c: _evaluate(c, final=True),
    default_status=DefaultScheduleStatus.STOPPED,
)
