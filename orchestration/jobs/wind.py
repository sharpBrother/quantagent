"""Wind 源刷新与日更作业。行情采集不依赖日历。"""

from dagster import AssetSelection, define_asset_job, multiprocess_executor

from orchestration.assets.wind import (
    WIND_SOURCE_ASSETS,
    src_wind_asharecalendar,
    src_wind_ashareeodprices,
    std_trade_calendar,
)

wind_source_refresh = define_asset_job(
    name="wind_source_refresh",
    selection=AssetSelection.assets(
        src_wind_asharecalendar,
        std_trade_calendar,
        src_wind_ashareeodprices,
    ),
)
# 并发上限 2：避免同时打开过多 Wind 连接。资金流已观察到吞吐偏低，多开连接不会加快总耗时。
wind_source_daily = define_asset_job(
    name="wind_source_daily",
    selection=AssetSelection.assets(*WIND_SOURCE_ASSETS, std_trade_calendar),
    executor_def=multiprocess_executor.configured({"max_concurrent": 2}),
)
