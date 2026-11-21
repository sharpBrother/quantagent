"""GPR 日频资产。公开源按自然日跑，不做交易日判断，也不按 as_of 切片：文件总是全量历史。
业务实现在函数体内导入，控制 daemon 导入耗时（见 ``orchestration/__init__.py``）。
不使用 ``from __future__ import annotations``：Dagster 要在导入时解析 Config 的注解。
"""

from dagster import Config, MaterializeResult, asset

from orchestration.assets.wind import _pit_grade

_GROUP = "macro"
_DATASET = "src.macro.gpr_daily"


class MacroGprRunConfig(Config):
    # 调度是全自动写入，与 Tushare 日更一致。第二道闸 QUANTAGENT_ALLOW_DB_WRITE 仍由执行机环境决定。
    write_db: bool = False


@asset(
    name="src_macro_gpr_daily",
    group_name=_GROUP,
    metadata={
        "reads": "iacoviello.gpr_daily_recent",
        "checkpoint": "src_macro_gpr_file_sha256",
        "pit_grade": _pit_grade(_DATASET),
    },
)
def src_macro_gpr_daily(config: MacroGprRunConfig) -> MaterializeResult[None]:
    from quantagent.ingest.jobs.macro_gpr import ingest_macro_gpr
    from quantagent.platform.config import get_settings
    from quantagent.platform.storage import detect_repo_root, resolve_var_paths

    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    result = ingest_macro_gpr(settings=settings, paths=paths, write_db=config.write_db)
    return MaterializeResult(
        metadata={
            "file_vintage": result.file_vintage.isoformat(),
            "observation_min": result.observation_min.isoformat(),
            "observation_max": result.observation_max.isoformat(),
            "unchanged": result.unchanged,
            "written": result.written,
            "row_count": result.row_count,
            "inserted": result.inserted,
            "replaced": result.replaced,
            "skipped": result.skipped,
            "metadata_skipped": result.metadata_skipped,
            "dml_count": result.dml_count,
            "file_sha256": result.file_sha256,
            "pit_grade": _pit_grade(_DATASET),
            "digest": result.output_digest or "",
        }
    )


class MacroFredRunConfig(Config):
    # 全量拉取，不需要起点或 as_of。第二道闸 QUANTAGENT_ALLOW_DB_WRITE 仍由执行机环境决定。
    write_db: bool = False


class MacroWgcRunConfig(Config):
    write_db: bool = False


@asset(
    name="src_macro_wgc_gold_demand",
    group_name=_GROUP,
    metadata={"pit_grade": _pit_grade("src.macro.macro_wgc_gold_demand")},
)
def src_macro_wgc_gold_demand(config: MacroWgcRunConfig) -> MaterializeResult[None]:
    from quantagent.ingest.jobs.macro_wgc_html import ingest_wgc_html
    from quantagent.platform.config import get_settings
    from quantagent.platform.storage import detect_repo_root, resolve_var_paths

    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    rows, new, sha = ingest_wgc_html(settings=settings, paths=paths, write_db=config.write_db)
    return MaterializeResult(
        metadata={
            "rows": rows,
            "new": new,
            "file_sha256": sha,
            "pit_grade": _pit_grade("src.macro.macro_wgc_gold_demand"),
        }
    )


@asset(
    name="src_macro_fred_observation_vintage",
    group_name=_GROUP,
    metadata={
        "reads": "fred.series/observations (realtime 1776-07-04..9999-12-31)",
        "checkpoint": "none_full_pull",
        "pit_grade": _pit_grade("src.macro.fred_observation_vintage"),
    },
)
def src_macro_fred_observation_vintage(config: MacroFredRunConfig) -> MaterializeResult[None]:
    from quantagent.ingest.jobs.macro_fred import ingest_macro_fred
    from quantagent.platform.config import get_settings
    from quantagent.platform.storage import detect_repo_root, resolve_var_paths

    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    result = ingest_macro_fred(settings=settings, paths=paths, write_db=config.write_db)
    return MaterializeResult(
        metadata={
            "series": ",".join(item.series_id for item in result.series),
            "pages": sum(item.pages for item in result.series),
            "row_count": result.row_count,
            "inserted": result.inserted,
            "replaced": result.replaced,
            "skipped": result.skipped,
            "metadata_skipped": result.metadata_skipped,
            "dml_count": result.dml_count,
            "pit_grade": _pit_grade("src.macro.fred_observation_vintage"),
            "digest": ",".join(item.write.output_digest for item in result.series),
        }
    )
