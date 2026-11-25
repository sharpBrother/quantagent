"""日更因子与前瞻收益调度。只在 local profile 注册（见 ``orchestration/definitions.py``）。

时间沿用旧仓 ``task_scheduler/jobs.json``，并随新 Wind 日更调整：
- 前瞻收益 17:30（旧 16:10 随 wind_to_sql_2 刷新），00:00、02:00 补跑；新 Wind 日更在 16:30 完成。
- 分钟因子 19:30（旧 factor_min）。
- 主因子 04:10（旧 factor_main）。
- UMR 04:30（旧 gruosen_umr，依赖分钟因子与行情）。

按 SSE 交易日历触发，非交易日跳过。同一作业上一轮未结束则跳过。
增量本身按就绪判定与 lake 水位线决定写什么，多次触发是幂等的：没有新数据时正常结束。
"""

from typing import TYPE_CHECKING
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

from orchestration.jobs.daily_feature import (
    DAILY_FEATURE_JOB_ASSETS,
    feature_daily_main,
    feature_forward_return_daily,
    feature_minute_daily,
    feature_umr_daily,
)
from quantagent.platform.config import get_settings
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

if TYPE_CHECKING:
    # define_asset_job 的返回类型未在 dagster 顶层导出，这里只用于标注。
    from dagster._core.definitions.unresolved_asset_job_definition import (
        UnresolvedAssetJobDefinition,
    )

_TZ = "Asia/Shanghai"
_EXCHANGE = "SSE"
_ACTIVE_STATUSES = [
    DagsterRunStatus.QUEUED,
    DagsterRunStatus.NOT_STARTED,
    DagsterRunStatus.STARTING,
    DagsterRunStatus.STARTED,
]


def _evaluate(
    context: ScheduleEvaluationContext,
    *,
    schedule_name: str,
    job: "UnresolvedAssetJobDefinition",
) -> RunRequest | SkipReason:
    if context.scheduled_execution_time is None:
        raise ValueError(f"{schedule_name} 缺少 scheduled_execution_time，拒绝猜测交易日")
    if context.instance.get_runs(
        filters=RunsFilter(job_name=job.name, statuses=_ACTIVE_STATUSES), limit=1
    ):
        return SkipReason(f"{job.name} 上一轮尚未结束，本次跳过")
    today = context.scheduled_execution_time.astimezone(ZoneInfo(_TZ)).date()
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    # 日历读取出错不吞掉：让 tick 报错，不在日历不可信时默认跑或默认跳过。
    from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
    from quantagent.domain.calendar.queries import CalendarQueries

    calendar = CalendarQueries(LakeCalendarRepository(paths.lake / "std" / "trade_calendar"))
    if not calendar.is_open(exchange=_EXCHANGE, cal_dt=today, as_of=today):
        return SkipReason(f"{today.isoformat()} 非 {_EXCHANGE} 交易日")
    ops = {
        asset.op.name: {"config": {"as_of": today.isoformat()}}
        for asset in DAILY_FEATURE_JOB_ASSETS[job.name]
    }
    return RunRequest(
        # 运行键带上触发时刻：同一天的 17:30、00:00、02:00 是三次独立的触发。
        run_key=f"{schedule_name}:{context.scheduled_execution_time.isoformat()}",
        run_config={"ops": ops},
    )


def _schedule(
    name: str,
    cron_schedule: str | list[str],
    job: "UnresolvedAssetJobDefinition",
) -> ScheduleDefinition:
    def _evaluation(context: ScheduleEvaluationContext) -> RunRequest | SkipReason:
        return _evaluate(context, schedule_name=name, job=job)

    return ScheduleDefinition(
        name=name,
        cron_schedule=cron_schedule,
        job=job,
        execution_timezone=_TZ,
        execution_fn=_evaluation,
        # 全自动：daemon 一启动调度即生效，与其他本机日更调度一致。
        default_status=DefaultScheduleStatus.RUNNING,
    )


feature_forward_return_daily_schedule = _schedule(
    "feature_forward_return_daily",
    ["30 17 * * *", "0 0 * * *", "0 2 * * *"],
    feature_forward_return_daily,
)
feature_minute_daily_schedule = _schedule(
    "feature_minute_daily", "30 19 * * *", feature_minute_daily
)
feature_daily_main_schedule = _schedule("feature_daily_main", "10 4 * * *", feature_daily_main)
feature_umr_daily_schedule = _schedule("feature_umr_daily", "30 4 * * *", feature_umr_daily)
