"""调度按 profile 注册：映射内容、未知 profile 报错，以及与 PROFILE_WRITABLE_SCHEMAS 不漂移。

不导入业务实现，不连接数据库；只看 Dagster 定义与写入白名单常量。
"""

from __future__ import annotations

import pytest
from orchestration.definitions import PROFILE_SCHEDULES, defs, schedules_for_profile

from quantagent.ingest.writers.tables import PROFILE_WRITABLE_SCHEMAS

# 资产名前缀到源 schema 的对应。新增前缀时必须同步这里，否则下面的测试会失败而不是静默跳过。
_PREFIX_TO_SCHEMA = {
    "src_wind_": "src_wind",
    "src_tushare_": "src_tushare",
    "src_macro_": "src_macro",
    "src_jydb_": "src_jydb",
    "src_suntime_": "src_suntime",
    "src_eastmoney_": "src_minprice",
    "src_mysql_": "src_minprice",
}
# lake 产物，不写源 schema，不受 PROFILE_WRITABLE_SCHEMAS 约束。
_LAKE_ASSETS = frozenset(
    {
        "std_trade_calendar",
        "feature_daily_forward_return",
        "feature_daily_cutamp",
        "feature_daily_mif",
        "feature_daily_moneyflowh",
        "feature_daily_actlargemedcut",
        "feature_daily_abso_umr",
        "feature_daily_tr_umr",
        "feature_daily_corr_vrlag",
        "feature_daily_real_kurt",
        "feature_daily_ratio_realupvar",
        "feature_daily_ratio_realdownvar",
        "feature_daily_corr_vrlaglarge",
        "feature_daily_core_up",
        "feature_daily_core_down",
        "feature_daily_did_ratio",
        "feature_daily_nap_adj_ratio",
        "feature_daily_event_sue",
        "feature_daily_event_aog",
        "feature_daily_event_delta_roe",
    }
)

_EXPECTED_SCHEDULES = {
    "office": set(),
    "local": {
        "wind_source_daily_close",
        "wind_source_daily_morning",
        "tushare_daily_evening",
        "macro_daily_morning",
        "macro_wgc_sunday",
        "minprice_first",
        "minprice_retry",
        "jydb_daily_night",
        "suntime_daily_night",
        "feature_forward_return_daily",
        "feature_minute_daily",
        "feature_daily_main",
        "feature_umr_daily",
    },
}


def _schema_of(asset_name: str) -> str | None:
    if asset_name in _LAKE_ASSETS:
        return None
    for prefix, schema in _PREFIX_TO_SCHEMA.items():
        if asset_name.startswith(prefix):
            return schema
    raise AssertionError(f"资产 {asset_name} 无法从前缀推出源 schema，请更新 _PREFIX_TO_SCHEMA")


def _job_asset_names(job_name: str) -> set[str]:
    job = defs.resolve_job_def(job_name)
    return {key.path[-1] for key in job.asset_layer.executable_asset_keys}


@pytest.mark.unit
@pytest.mark.parametrize("profile", ["office", "local"])
def test_profile_selects_expected_schedules(profile: str) -> None:
    names = {schedule.name for schedule in schedules_for_profile(profile)}
    assert names == _EXPECTED_SCHEDULES[profile]


@pytest.mark.unit
def test_unknown_profile_is_rejected() -> None:
    with pytest.raises(ValueError, match="未知 QUANTAGENT_PROFILE"):
        schedules_for_profile("laptop")


@pytest.mark.unit
def test_every_registered_schedule_belongs_to_some_profile() -> None:
    # 四个调度都必须归属某个 profile，否则会出现谁都不跑的调度。
    mapped = {s.name for schedules in PROFILE_SCHEDULES.values() for s in schedules}
    assert mapped == {
        "wind_source_daily_close",
        "wind_source_daily_morning",
        "tushare_daily_evening",
        "macro_daily_morning",
        "macro_wgc_sunday",
        "minprice_first",
        "minprice_retry",
        "jydb_daily_night",
        "suntime_daily_night",
        "feature_forward_return_daily",
        "feature_minute_daily",
        "feature_daily_main",
        "feature_umr_daily",
    }


@pytest.mark.unit
def test_profile_keys_match_writable_schemas() -> None:
    # 两处映射的 profile 集合必须一致，否则一边新增 profile 另一边漏掉。
    assert set(PROFILE_SCHEDULES) == set(PROFILE_WRITABLE_SCHEMAS)


@pytest.mark.unit
def test_definitions_registers_only_current_profile_schedules() -> None:
    # defs 在导入时按当时的 profile 选调度，导入早于测试夹具，这里只断言它是某一台机器的完整集合。
    current = {s.name for s in defs.schedules or []}
    assert current in _EXPECTED_SCHEDULES.values()


@pytest.mark.unit
@pytest.mark.parametrize("profile", ["office", "local"])
def test_scheduled_jobs_only_write_schemas_writable_by_profile(profile: str) -> None:
    writable = PROFILE_WRITABLE_SCHEMAS[profile]
    for schedule in schedules_for_profile(profile):
        for asset_name in _job_asset_names(schedule.job.name):
            schema = _schema_of(asset_name)
            if schema is None:
                continue
            assert schema in writable, (
                f"调度 {schedule.name} 的作业含资产 {asset_name}（写 {schema}），"
                f"但 profile={profile} 只允许写 {sorted(writable)}"
            )
