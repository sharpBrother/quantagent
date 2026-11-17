"""Wind 日更调度。按 SSE 交易日历触发，非交易日不跑。

两个调度跑同一个作业 ``wind_source_daily``，共用"上一轮未结束则跳过"的检查，
避免首次全量回填（数小时）与下一次触发叠跑。
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

from orchestration.assets.wind import WIND_SOURCE_ASSETS, std_trade_calendar
from orchestration.jobs.wind import wind_source_daily
from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.domain.calendar.queries import CalendarQueries
from quantagent.platform.config import get_settings
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

_TZ = "Asia/Shanghai"
_EXCHANGE = "SSE"
_ACTIVE_STATUSES = [
    DagsterRunStatus.QUEUED,
    DagsterRunStatus.NOT_STARTED,
    DagsterRunStatus.STARTING,
    DagsterRunStatus.STARTED,
]


def _has_active_run(context: ScheduleEvaluationContext) -> bool:
    runs = context.instance.get_runs(
        filters=RunsFilter(job_name=wind_source_daily.name, statuses=_ACTIVE_STATUSES),
        limit=1,
    )
    return bool(runs)


def _run_config(today: str) -> dict[str, object]:
    ops: dict[str, object] = {}
    for asset in WIND_SOURCE_ASSETS:
        ops[asset.op.name] = {
            "config": {
                "as_of": today,
                # 调度是负责人裁定的全自动写入（2026-11-17）。第二道闸 QUANTAGENT_ALLOW_DB_WRITE
                # 仍由执行机环境决定，环境变量为 false 时写入会被拒绝。
                "write_db": True,
                "max_pages": None,
                "page_size": 10000,
            }
        }
    ops[std_trade_calendar.op.name] = {
        "config": {"as_of": today, "rebuild": False, "skip_if_unchanged": True}
    }
    return {"ops": ops}


def _evaluate(context: ScheduleEvaluationContext, schedule_name: str) -> RunRequest | SkipReason:
    if context.scheduled_execution_time is None:
        raise ValueError(f"{schedule_name} 缺少 scheduled_execution_time，拒绝猜测交易日")
    if _has_active_run(context):
        return SkipReason(f"{wind_source_daily.name} 上一轮尚未结束，本次跳过")

    today = context.scheduled_execution_time.astimezone(ZoneInfo(_TZ)).date()
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    # 日历读取出错不吞掉：让 tick 报错，不在日历不可信时默认跑或默认跳过。
    calendar = CalendarQueries(LakeCalendarRepository(paths.lake / "std" / "trade_calendar"))
    if not calendar.is_open(exchange=_EXCHANGE, cal_dt=today, as_of=today):
        return SkipReason(f"{today.isoformat()} 非 {_EXCHANGE} 交易日")

    return RunRequest(
        run_key=f"{schedule_name}:{today.isoformat()}",
        run_config=_run_config(today.isoformat()),
    )


def build_wind_daily_schedule(name: str, cron_schedule: str) -> ScheduleDefinition:
    def _evaluation(context: ScheduleEvaluationContext) -> RunRequest | SkipReason:
        return _evaluate(context, name)

    return ScheduleDefinition(
        name=name,
        cron_schedule=cron_schedule,
        job=wind_source_daily,
        execution_timezone=_TZ,
        execution_fn=_evaluation,
        # 全自动：daemon 一启动调度即生效，不需要在 UI 里手动打开。
        default_status=DefaultScheduleStatus.RUNNING,
    )


# 旧仓 wind_to_sql_2 的收盘后批次。
wind_source_daily_close = build_wind_daily_schedule("wind_source_daily_close", "30 16 * * *")
# 旧仓 wind_to_sql_am 的早间财报与预告批次。
wind_source_daily_morning = build_wind_daily_schedule("wind_source_daily_morning", "0 6 * * *")
