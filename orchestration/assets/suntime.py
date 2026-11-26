"""朝阳永续 P0/P1 源镜像资产。首次运行全量回填，此后从共享游标增量。

业务实现函数体内导入，控制 daemon 导入耗时。小表在前、大表在后串行；
每次调用都从 ``src_suntime._batch.source_cursor`` 续跑，不另存水位。
"""

from dagster import AssetExecutionContext, Config, MaterializeResult, asset

from orchestration.assets.wind import _pit_grade

_GROUP = "suntime"


class SuntimeRunConfig(Config):
    write_db: bool = False
    page_size: int = 1000
    max_pages: int | None = None


# 只建镜像、不写可见性契约的表。没有契约就不能报一个 PIT 等级。
_MIRROR_ONLY = frozenset({"rpt_earnings_adjust"})


def _ingest(
    context: AssetExecutionContext, table: str, config: SuntimeRunConfig
) -> MaterializeResult[None]:
    # 采集在看门狗保护的子进程里跑，超时终止时抛 IngestStalledError，资产失败、队列释放。
    # 页进度日志改由父进程失败记录与 Dagster 事件时间线承担；成功路径的页数进 metadata。
    from orchestration.resources.suntime import SuntimeIngestResource
    from quantagent.platform.config import get_settings
    from quantagent.platform.storage import detect_repo_root, resolve_var_paths

    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    context.log.info("%s 开始采集（看门狗子进程），每页 %s 行", table, config.page_size)
    result = SuntimeIngestResource(settings=settings, paths=paths).ingest(
        table,
        write_db=config.write_db,
        page_size=config.page_size,
        max_pages=config.max_pages,
    )
    context.log.info("%s 采集结束，共 %s 页", table, result.pages)
    return MaterializeResult(
        metadata={
            "dataset": result.dataset,
            "pages": result.pages,
            "row_count": result.row_count,
            "inserted": result.inserted,
            "replaced": result.replaced,
            "skipped": result.skipped,
            "metadata_skipped": result.metadata_skipped,
            "dml_count": result.dml_count,
            "source_cursor": result.source_cursor,
            "pit_grade": "not_pit" if table in _MIRROR_ONLY else _pit_grade(result.dataset),
            "digest": result.payload_digest,
        }
    )


@asset(
    name="src_suntime_con_forecast_roll_idx",
    group_name=_GROUP,
    metadata={
        "reads": "suntime.con_forecast_roll_idx",
        "checkpoint": "src_batch_source_cursor",
    },
)
def src_suntime_con_forecast_roll_idx(
    context: AssetExecutionContext, config: SuntimeRunConfig
) -> MaterializeResult[None]:
    return _ingest(context, "con_forecast_roll_idx", config)


@asset(
    name="src_suntime_con_forecast_idx",
    group_name=_GROUP,
    deps=[src_suntime_con_forecast_roll_idx],
    metadata={"reads": "suntime.con_forecast_idx", "checkpoint": "src_batch_source_cursor"},
)
def src_suntime_con_forecast_idx(
    context: AssetExecutionContext, config: SuntimeRunConfig
) -> MaterializeResult[None]:
    return _ingest(context, "con_forecast_idx", config)


@asset(
    name="src_suntime_rpt_earnings_adjust",
    group_name=_GROUP,
    deps=[src_suntime_con_forecast_idx],
    metadata={"reads": "suntime.rpt_earnings_adjust", "checkpoint": "src_batch_source_cursor"},
)
def src_suntime_rpt_earnings_adjust(
    context: AssetExecutionContext, config: SuntimeRunConfig
) -> MaterializeResult[None]:
    return _ingest(context, "rpt_earnings_adjust", config)


@asset(
    name="src_suntime_fin_performance_forecast",
    group_name=_GROUP,
    deps=[src_suntime_rpt_earnings_adjust],
    metadata={
        "reads": "suntime.fin_performance_forecast",
        "checkpoint": "src_batch_source_cursor",
    },
)
def src_suntime_fin_performance_forecast(
    context: AssetExecutionContext, config: SuntimeRunConfig
) -> MaterializeResult[None]:
    return _ingest(context, "fin_performance_forecast", config)


@asset(
    name="src_suntime_fin_performance_express",
    group_name=_GROUP,
    deps=[src_suntime_fin_performance_forecast],
    metadata={
        "reads": "suntime.fin_performance_express",
        "checkpoint": "src_batch_source_cursor",
    },
)
def src_suntime_fin_performance_express(
    context: AssetExecutionContext, config: SuntimeRunConfig
) -> MaterializeResult[None]:
    return _ingest(context, "fin_performance_express", config)


@asset(
    name="src_suntime_fin_income_gen",
    group_name=_GROUP,
    deps=[src_suntime_fin_performance_express],
    metadata={"reads": "suntime.fin_income_gen", "checkpoint": "src_batch_source_cursor"},
)
def src_suntime_fin_income_gen(
    context: AssetExecutionContext, config: SuntimeRunConfig
) -> MaterializeResult[None]:
    return _ingest(context, "fin_income_gen", config)


@asset(
    name="src_suntime_con_forecast_roll_stk",
    group_name=_GROUP,
    deps=[src_suntime_fin_income_gen],
    metadata={"reads": "suntime.con_forecast_roll_stk", "checkpoint": "src_batch_source_cursor"},
)
def src_suntime_con_forecast_roll_stk(
    context: AssetExecutionContext, config: SuntimeRunConfig
) -> MaterializeResult[None]:
    return _ingest(context, "con_forecast_roll_stk", config)


@asset(
    name="src_suntime_con_forecast_stk",
    group_name=_GROUP,
    deps=[src_suntime_con_forecast_roll_stk],
    metadata={"reads": "suntime.con_forecast_stk", "checkpoint": "src_batch_source_cursor"},
)
def src_suntime_con_forecast_stk(
    context: AssetExecutionContext, config: SuntimeRunConfig
) -> MaterializeResult[None]:
    return _ingest(context, "con_forecast_stk", config)
