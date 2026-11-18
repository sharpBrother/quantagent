"""Tushare shibor 日更资产。

这个作业只在 Mac（``QUANTAGENT_PROFILE=local``）上跑。公司电脑的 profile 是 ``office``，
写入 ``src_tushare`` 会被 ``assert_writable`` 拒绝，所以在公司电脑上跑只会失败，不会误写。

起点不由配置给出。它读 ``src_tushare._batch`` 里最近成功批次的 ``window_end``，往前回看 30 天，
用来重查近期修订。业务实现在函数体内导入，控制 daemon 导入耗时（见 ``orchestration/__init__.py``）。
不使用 ``from __future__ import annotations``：Dagster 要在导入时解析 Config 的注解。
"""

from datetime import datetime

from dagster import Config, MaterializeResult, asset

from orchestration.assets.wind import _pit_grade

_GROUP = "tushare"
_DATASET = "src.tushare.shibor"


class TushareShiborRunConfig(Config):
    as_of: str
    # 调度是全自动写入，与 Wind 日更一致。第二道闸 QUANTAGENT_ALLOW_DB_WRITE 仍由执行机环境决定。
    write_db: bool = False


def _as_of(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"as_of 必须是 YYYY-MM-DD: {value}") from exc


@asset(
    name="src_tushare_shibor",
    group_name=_GROUP,
    metadata={
        "reads": "tushare.shibor",
        "checkpoint": "src_batch_window_end",
        "pit_grade": _pit_grade(_DATASET),
    },
)
def src_tushare_shibor(config: TushareShiborRunConfig) -> MaterializeResult[None]:
    from quantagent.ingest.jobs.tushare_shibor import (
        ingest_tushare_shibor,
        resolve_daily_start,
    )
    from quantagent.platform.config import get_settings
    from quantagent.platform.storage import detect_repo_root, resolve_var_paths

    end = _as_of(config.as_of)
    end_date = end.strftime("%Y%m%d")
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    start_date = resolve_daily_start(settings=settings, end_date=end_date)
    result = ingest_tushare_shibor(
        settings=settings,
        paths=paths,
        write_db=config.write_db,
        start_date=start_date,
        end_date=end_date,
    )
    return MaterializeResult(
        metadata={
            "as_of": end.date().isoformat(),
            "start_date": start_date,
            "segments": result.segments,
            "empty_segments": ",".join(result.empty_segments) or "无",
            "row_count": result.row_count,
            "inserted": result.inserted,
            "replaced": result.replaced,
            "skipped": result.skipped,
            "metadata_skipped": result.metadata_skipped,
            "dml_count": result.dml_count,
            "pit_grade": _pit_grade(_DATASET),
            "digest": result.output_digest,
        }
    )
