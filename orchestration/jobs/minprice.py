from dagster import AssetSelection, define_asset_job

from orchestration.assets.minprice import src_mysql_minute

minprice_daily = define_asset_job(
    name="minprice_daily", selection=AssetSelection.assets(src_mysql_minute)
)
