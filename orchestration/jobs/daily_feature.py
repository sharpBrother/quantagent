"""日更增量作业。每个作业内的资产串行执行（一次一个），与其他日更作业的执行方式一致。

分组按调度时间：前瞻收益、分钟因子、主因子、UMR 各一个作业，互不依赖，可以各自独立重跑。
"""

from dagster import AssetsDefinition, AssetSelection, define_asset_job, multiprocess_executor

from orchestration.assets.daily_feature import FEATURE_DAILY_ASSETS, feature_daily_forward_return

_SERIAL = multiprocess_executor.configured({"max_concurrent": 1})

_MINUTE = (
    "feature_daily_corr_vrlag",
    "feature_daily_real_kurt",
    "feature_daily_ratio_realupvar",
    "feature_daily_ratio_realdownvar",
    "feature_daily_corr_vrlaglarge",
    "feature_daily_core_up",
    "feature_daily_core_down",
)
_MAIN = (
    "feature_daily_cutamp",
    "feature_daily_mif",
    "feature_daily_moneyflowh",
    "feature_daily_actlargemedcut",
    "feature_daily_did_ratio",
    "feature_daily_nap_adj_ratio",
)
_UMR = ("feature_daily_tr_umr", "feature_daily_abso_umr")


def _assets(names: tuple[str, ...]) -> list[AssetsDefinition]:
    return [FEATURE_DAILY_ASSETS[name] for name in names]


feature_forward_return_daily = define_asset_job(
    name="feature_forward_return_daily",
    selection=AssetSelection.assets(feature_daily_forward_return),
    executor_def=_SERIAL,
)

feature_minute_daily = define_asset_job(
    name="feature_minute_daily",
    selection=AssetSelection.assets(*_assets(_MINUTE)),
    executor_def=_SERIAL,
)

feature_daily_main = define_asset_job(
    name="feature_daily_main",
    selection=AssetSelection.assets(*_assets(_MAIN)),
    executor_def=_SERIAL,
)

feature_umr_daily = define_asset_job(
    name="feature_umr_daily",
    selection=AssetSelection.assets(*_assets(_UMR)),
    executor_def=_SERIAL,
)

# 调度用：每个作业包含的资产，供 run_config 逐个给出 as_of。
DAILY_FEATURE_JOB_ASSETS: dict[str, tuple[AssetsDefinition, ...]] = {
    feature_forward_return_daily.name: (feature_daily_forward_return,),
    feature_minute_daily.name: tuple(_assets(_MINUTE)),
    feature_daily_main.name: tuple(_assets(_MAIN)),
    feature_umr_daily.name: tuple(_assets(_UMR)),
}
