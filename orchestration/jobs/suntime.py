"""朝阳永续 P0/P1 日更作业。串行，一次一条源库和一条目标库连接。"""

from dagster import AssetSelection, define_asset_job, multiprocess_executor

from orchestration.assets.suntime import (
    src_suntime_con_forecast_idx,
    src_suntime_con_forecast_roll_idx,
    src_suntime_con_forecast_roll_stk,
    src_suntime_con_forecast_stk,
    src_suntime_rpt_earnings_adjust,
)

suntime_daily = define_asset_job(
    name="suntime_daily",
    selection=AssetSelection.assets(
        src_suntime_con_forecast_roll_idx,
        src_suntime_con_forecast_idx,
        src_suntime_rpt_earnings_adjust,
        src_suntime_con_forecast_roll_stk,
        src_suntime_con_forecast_stk,
    ),
    executor_def=multiprocess_executor.configured({"max_concurrent": 1}),
)
