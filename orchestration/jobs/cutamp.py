"""切段振幅手工物化。不放进 Wind 源刷新，避免顺带重跑采集。"""

from dagster import AssetSelection, define_asset_job

from orchestration.assets.cutamp import feature_pf_single_cutamp

feature_cutamp = define_asset_job(
    name="feature_cutamp",
    selection=AssetSelection.assets(feature_pf_single_cutamp),
)
