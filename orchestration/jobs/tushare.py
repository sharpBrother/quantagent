"""Tushare 日更作业。只在 Mac（profile=local）上跑，见 ``orchestration/assets/tushare.py``。"""

from dagster import AssetSelection, define_asset_job

from orchestration.assets.tushare import src_tushare_shibor

tushare_daily = define_asset_job(
    name="tushare_daily",
    selection=AssetSelection.assets(src_tushare_shibor),
)
