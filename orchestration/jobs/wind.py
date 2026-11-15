"""Wind 源刷新：日历采集、标准日历物化、日行情采集。行情采集不依赖日历。"""

from dagster import AssetSelection, define_asset_job

from orchestration.assets.wind import (
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
