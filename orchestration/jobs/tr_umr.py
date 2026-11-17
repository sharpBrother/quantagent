"""真实波幅 UMR 手工物化。不放进 Wind 源刷新，避免顺带重跑采集。"""

from dagster import AssetSelection, define_asset_job

from orchestration.assets.tr_umr import feature_pf_single_tr_umr

feature_tr_umr = define_asset_job(
    name="feature_tr_umr",
    selection=AssetSelection.assets(feature_pf_single_tr_umr),
)
