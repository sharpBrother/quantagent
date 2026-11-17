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
# 串行：执行机经 ToDesk 端口转发连 PG。2026-11-17 两个资产并发时出现回读截在第 2,500 行、
# 参数里混入 0x8d 半个多字节字符，单跑同一页都通过，按链路在并发下截断处理。
wind_source_daily = define_asset_job(
    name="wind_source_daily",
    selection=AssetSelection.assets(*WIND_SOURCE_ASSETS, std_trade_calendar),
    executor_def=multiprocess_executor.configured({"max_concurrent": 1}),
)
