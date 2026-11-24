"""聚源 JYDB P0/P1 日更作业。串行，一次一条源库和一条目标库连接。"""

from dagster import AssetSelection, define_asset_job, multiprocess_executor

from orchestration.assets.jydb import (
    src_jydb_c_ed_indicatormain,
    src_jydb_c_ed_macroindicatordata,
    src_jydb_c_in_indicatordatav,
    src_jydb_c_in_indicatormain,
    src_jydb_ed_moneysupply,
    src_jydb_qt_osindexquote,
)

jydb_daily = define_asset_job(
    name="jydb_daily",
    selection=AssetSelection.assets(
        src_jydb_c_ed_indicatormain,
        src_jydb_c_ed_macroindicatordata,
        src_jydb_c_in_indicatormain,
        src_jydb_c_in_indicatordatav,
        src_jydb_ed_moneysupply,
        src_jydb_qt_osindexquote,
    ),
    executor_def=multiprocess_executor.configured({"max_concurrent": 1}),
)
