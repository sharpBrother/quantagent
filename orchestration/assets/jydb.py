"""聚源 JYDB P0/P1 源镜像资产。首次运行全量回填，此后从共享游标增量。

业务实现函数体内导入，控制 daemon 导入耗时。资产按目录表在前、数据表在后的
顺序串行；每次调用都从 ``src_jydb._batch.source_cursor`` 续跑，不另存水位。
"""

from dagster import Config, MaterializeResult, asset

from orchestration.assets.wind import _pit_grade

_GROUP = "jydb"


class JydbRunConfig(Config):
    write_db: bool = False
    page_size: int = 1000
    max_pages: int | None = None


_CATALOG_TABLES = frozenset({"C_ED_IndicatorMain", "C_IN_IndicatorMain"})


def _ingest(table: str, config: JydbRunConfig) -> MaterializeResult[None]:
    from quantagent.ingest.jobs.jydb_paged import ingest_jydb_paged
    from quantagent.platform.config import get_settings
    from quantagent.platform.storage import detect_repo_root, resolve_var_paths

    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    result = ingest_jydb_paged(
        settings=settings,
        paths=paths,
        table=table,
        write_db=config.write_db,
        page_size=config.page_size,
        max_pages=config.max_pages,
    )
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
            "pit_grade": "not_pit" if table in _CATALOG_TABLES else _pit_grade(result.dataset),
            "digest": result.payload_digest,
        }
    )


@asset(
    name="src_jydb_c_ed_indicatormain",
    group_name=_GROUP,
    metadata={"reads": "jydb.C_ED_IndicatorMain", "checkpoint": "src_batch_source_cursor"},
)
def src_jydb_c_ed_indicatormain(config: JydbRunConfig) -> MaterializeResult[None]:
    return _ingest("C_ED_IndicatorMain", config)


@asset(
    name="src_jydb_c_ed_macroindicatordata",
    group_name=_GROUP,
    deps=[src_jydb_c_ed_indicatormain],
    metadata={"reads": "jydb.C_ED_MacroIndicatorData", "checkpoint": "src_batch_source_cursor"},
)
def src_jydb_c_ed_macroindicatordata(config: JydbRunConfig) -> MaterializeResult[None]:
    return _ingest("C_ED_MacroIndicatorData", config)


@asset(
    name="src_jydb_c_in_indicatormain",
    group_name=_GROUP,
    deps=[src_jydb_c_ed_macroindicatordata],
    metadata={"reads": "jydb.C_IN_IndicatorMain", "checkpoint": "src_batch_source_cursor"},
)
def src_jydb_c_in_indicatormain(config: JydbRunConfig) -> MaterializeResult[None]:
    return _ingest("C_IN_IndicatorMain", config)


@asset(
    name="src_jydb_c_in_indicatordatav",
    group_name=_GROUP,
    deps=[src_jydb_c_in_indicatormain],
    metadata={"reads": "jydb.C_IN_IndicatorDataV", "checkpoint": "src_batch_source_cursor"},
)
def src_jydb_c_in_indicatordatav(config: JydbRunConfig) -> MaterializeResult[None]:
    return _ingest("C_IN_IndicatorDataV", config)


@asset(
    name="src_jydb_ed_moneysupply",
    group_name=_GROUP,
    deps=[src_jydb_c_in_indicatordatav],
    metadata={"reads": "jydb.ED_MoneySupply", "checkpoint": "src_batch_source_cursor"},
)
def src_jydb_ed_moneysupply(config: JydbRunConfig) -> MaterializeResult[None]:
    return _ingest("ED_MoneySupply", config)
