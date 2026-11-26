"""run 失败告警 sensor：把每次失败落进 ``var/logs/alerts/run_failures.jsonl``。

通知渠道（邮件 / 企业微信）负责人尚未裁定。sensor 本体不能等渠道——11-25 jydb 卡死
7 小时靠人工发现，先保证每次失败在 ``var/logs/alerts/`` 留下可读记录，
渠道接入后从同一文件消费。每日汇总由 ``quantagent alert summary`` CLI 生成
（手动或事后追加调度），因为 sensor 只感知失败事件，不产生"零异常"的全量视角。

只监控本地调度挂的日更作业：回填类一次性作业（wind_initial_backfill）失败由操作者当场看到，
不需要告警。sensor 自身失败不得拖垮 daemon，因此写文件出错只记日志不重抛。
"""

from __future__ import annotations

from datetime import UTC, datetime

from dagster import DefaultSensorStatus, RunFailureSensorContext, run_failure_sensor

from quantagent.platform.alerts import RunFailureAlert, append_failure_alert

# 与 PROFILE_SCHEDULES 的 local 调度一一对应。新增日更作业时必须加进这个集合，
# tests/unit/orchestration/test_run_failure_sensor.py 会对照调度定义防漂移。
MONITORED_JOB_NAMES: frozenset[str] = frozenset(
    {
        "wind_source_daily",
        "tushare_daily",
        "macro_daily",
        "macro_wgc_weekly",
        "minprice_daily",
        "jydb_daily",
        "suntime_daily",
        "feature_forward_return_daily",
        "feature_minute_daily",
        "feature_daily_main",
        "feature_umr_daily",
    }
)


def _failure_message(context: RunFailureSensorContext) -> tuple[str, str | None]:
    """取第一个 step 失败的错误摘要；run 级失败（无 step）退回 run 事件 message。"""
    step_events = context.get_step_failure_events()
    for event in step_events:
        error = event.step_failure_data.error if event.step_failure_data else None
        if error is not None:
            message = error.message.strip().splitlines()
            return (message[0][:500] if message else type(error).__name__), event.step_key
    run_message = context.failure_event.message or "run 失败，无错误消息"
    return run_message[:500], None


def record_run_failure(context: RunFailureSensorContext, alerts_path: object) -> None:
    """抽出来供单测直接调用：构造告警并追加。``alerts_path`` 用 object 注解避免导入期解析 Path 子类。"""
    from pathlib import Path

    message, step_key = _failure_message(context)
    alert = RunFailureAlert(
        recorded_at=datetime.now(UTC).isoformat(),
        dagster_run_id=context.dagster_run.run_id,
        job_name=context.dagster_run.job_name,
        run_status=context.dagster_run.status.value,
        failure_message=message,
        step_key=step_key,
        schedule_name=context.dagster_run.tags.get("dagster/schedule_name"),
    )
    append_failure_alert(alert, Path(str(alerts_path)))


@run_failure_sensor(
    name="run_failure_alert",
    description="日更作业 run 失败落 var/logs/alerts/run_failures.jsonl；通知渠道待负责人裁定",
    default_status=DefaultSensorStatus.RUNNING,
    minimum_interval_seconds=30,
)
def run_failure_alert(context: RunFailureSensorContext) -> None:
    if context.dagster_run.job_name not in MONITORED_JOB_NAMES:
        return
    from quantagent.platform.config import get_settings
    from quantagent.platform.logging import get_logger
    from quantagent.platform.storage import detect_repo_root, resolve_var_paths

    try:
        settings = get_settings()
        paths = resolve_var_paths(settings, repo_root=detect_repo_root())
        record_run_failure(context, paths.logs / "alerts" / "run_failures.jsonl")
    # sensor 失败不能拖垮 daemon，告警丢失由日志兜底；故捕全部异常不重抛。
    except Exception as exc:
        get_logger("orchestration").error(
            "run_failure_alert 落盘失败 run_id=%s: %s", context.dagster_run.run_id, exc
        )
        context.log.exception("run_failure_alert 落盘失败: %s", exc)


__all__ = ["MONITORED_JOB_NAMES", "record_run_failure", "run_failure_alert"]
