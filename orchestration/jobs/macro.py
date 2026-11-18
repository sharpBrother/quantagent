"""宏观公开源日更作业。目前只有 GPR。

串行：与 Wind 日更一样只允许同一时刻跑一个 step，避免同一 PG 连接链路上并发写入被截断。
与 Tushare 日更写不同 schema（``src_tushare`` 与 ``src_macro``），两者之间不做互斥。
"""

from dagster import AssetSelection, define_asset_job, multiprocess_executor

from orchestration.assets.macro import (
    src_macro_fred_observation_vintage,
    src_macro_gpr_daily,
    src_macro_wgc_gold_demand,
)

macro_daily = define_asset_job(
    name="macro_daily",
    selection=AssetSelection.assets(src_macro_gpr_daily, src_macro_fred_observation_vintage),
    executor_def=multiprocess_executor.configured({"max_concurrent": 1}),
)

macro_wgc_weekly = define_asset_job(
    name="macro_wgc_weekly",
    selection=AssetSelection.assets(src_macro_wgc_gold_demand),
    executor_def=multiprocess_executor.configured({"max_concurrent": 1}),
)
