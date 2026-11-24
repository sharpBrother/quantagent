"""聚源 JYDB 日更调度。每天 03:30（上海）触发；同一作业未结束时跳过。

按旧仓 ``task_scheduler/jobs.json`` 的 03:30 时点。聚源宏观表按自然日更新，
不依赖 A 股交易日历。只在能连聚源、且没有其他机器同时启用本调度的机器上运行。
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

from orchestration.assets.jydb import (
    src_jydb_c_ed_indicatormain,
    src_jydb_c_ed_macroindicatordata,
    src_jydb_c_in_indicatordatav,
    src_jydb_c_in_indicatormain,
    src_jydb_ed_moneysupply,
    src_jydb_qt_osindexquote,
)
from orchestration.jobs.jydb import jydb_daily

_TZ = "Asia/Shanghai"
_SCHEDULE_NAME = "jydb_daily_night"
_ACTIVE_STATUSES = [
    DagsterRunStatus.QUEUED,
    DagsterRunStatus.NOT_STARTED,
    DagsterRunStatus.STARTING,
    DagsterRunStatus.STARTED,
]
_ASSETS = (
    src_jydb_c_ed_indicatormain,
    src_jydb_c_ed_macroindicatordata,
    src_jydb_c_in_indicatormain,
    src_jydb_c_in_indicatordatav,
    src_jydb_ed_moneysupply,
    src_jydb_qt_osindexquote,
)


def _evaluate(context: ScheduleEvaluationContext) -> RunRequest | SkipReason:
    if context.scheduled_execution_time is None:
        raise ValueError(f"{_SCHEDULE_NAME} 缺少 scheduled_execution_time")
    active = context.instance.get_runs(
        filters=RunsFilter(job_name=jydb_daily.name, statuses=_ACTIVE_STATUSES),
        limit=1,
    )
    if active:
        return SkipReason(f"{jydb_daily.name} 上一轮尚未结束，本次跳过")
    day = context.scheduled_execution_time.astimezone(ZoneInfo(_TZ)).date().isoformat()
    return RunRequest(
        run_key=f"{_SCHEDULE_NAME}:{day}",
        run_config={
            "ops": {
                item.op.name: {"config": {"write_db": True, "page_size": 1000}} for item in _ASSETS
            }
        },
    )


jydb_daily_night = ScheduleDefinition(
    name=_SCHEDULE_NAME,
    cron_schedule="30 3 * * *",
    job=jydb_daily,
    execution_timezone=_TZ,
    execution_fn=_evaluate,
    default_status=DefaultScheduleStatus.RUNNING,
)
