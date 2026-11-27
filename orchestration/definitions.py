"""Dagster 入口。本地查看图：``dagster dev -m orchestration.definitions``。

运行存储由 ``DAGSTER_HOME`` 里的 ``dagster.yaml`` 决定，不在导入时连接控制库。
模板是 ``orchestration/dagster.yaml``：``search_path=ops``，关闭自建表。
"""

from __future__ import annotations

from dagster import Definitions, ScheduleDefinition

from orchestration.assets.cutamp import feature_pf_single_cutamp
from orchestration.assets.daily_feature import FEATURE_DAILY_ASSETS, feature_daily_forward_return
from orchestration.assets.jydb import (
    src_jydb_c_ed_indicatormain,
    src_jydb_c_ed_macroindicatordata,
    src_jydb_c_in_indicatordatav,
    src_jydb_c_in_indicatormain,
    src_jydb_ed_moneysupply,
    src_jydb_qt_osindexquote,
)
from orchestration.assets.macro import (
    src_macro_fred_observation_vintage,
    src_macro_gpr_daily,
    src_macro_jin10_economic_calendar,
    src_macro_wgc_gold_demand,
)
from orchestration.assets.minprice import src_eastmoney_minute, src_mysql_minute
from orchestration.assets.suntime import (
    src_suntime_con_forecast_idx,
    src_suntime_con_forecast_roll_idx,
    src_suntime_con_forecast_roll_stk,
    src_suntime_con_forecast_stk,
    src_suntime_fin_income_gen,
    src_suntime_fin_performance_express,
    src_suntime_fin_performance_forecast,
    src_suntime_rpt_earnings_adjust,
)
from orchestration.assets.tr_umr import feature_pf_single_tr_umr
from orchestration.assets.tushare import src_tushare_shibor, src_tushare_us_treasury_yield
from orchestration.assets.wind import WIND_SOURCE_ASSETS, std_trade_calendar
from orchestration.jobs.cutamp import feature_cutamp
from orchestration.jobs.daily_feature import (
    feature_daily_main,
    feature_forward_return_daily,
    feature_minute_daily,
    feature_umr_daily,
)
from orchestration.jobs.jydb import jydb_daily
from orchestration.jobs.macro import macro_daily, macro_wgc_weekly
from orchestration.jobs.minprice import minprice_daily
from orchestration.jobs.suntime import suntime_daily
from orchestration.jobs.tr_umr import feature_tr_umr
from orchestration.jobs.tushare import tushare_daily
from orchestration.jobs.wind import wind_source_daily, wind_source_refresh
from orchestration.jobs.wind_initial import wind_initial_backfill
from orchestration.resources.wind import TradeCalendarResource, WindIngestResource
from orchestration.schedules.daily_feature import (
    feature_daily_main_schedule,
    feature_forward_return_daily_schedule,
    feature_minute_daily_schedule,
    feature_umr_daily_schedule,
)
from orchestration.schedules.jydb import jydb_daily_night
from orchestration.schedules.macro import macro_daily_morning, macro_wgc_sunday
from orchestration.schedules.minprice import minprice_first, minprice_retry
from orchestration.schedules.suntime import suntime_daily_night
from orchestration.schedules.tushare import tushare_daily_evening
from orchestration.schedules.wind import wind_source_daily_close, wind_source_daily_morning
from orchestration.sensors.run_failure import run_failure_alert
from quantagent.platform.config import get_settings
from quantagent.platform.storage import detect_repo_root, resolve_var_paths


def _resources() -> dict[str, WindIngestResource | TradeCalendarResource]:
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    return {
        "wind_ingest": WindIngestResource(settings=settings, paths=paths),
        "trade_calendar": TradeCalendarResource(settings=settings, paths=paths),
    }


# 调度仍按 profile 注册，写入目标不再按机器限制。
# 各机队列独立，同一来源的自动采集只能在一台机器启用。
PROFILE_SCHEDULES: dict[str, tuple[ScheduleDefinition, ...]] = {
    # 负责人 2026-11-25：Wind、朝阳永续、聚源、Tushare、公开源与因子日更都挂在 Mac（local）。
    # 公司电脑不再注册调度，避免两边同时采集同一来源。
    "office": (),
    "local": (
        wind_source_daily_close,
        wind_source_daily_morning,
        tushare_daily_evening,
        macro_daily_morning,
        macro_wgc_sunday,
        minprice_first,
        minprice_retry,
        jydb_daily_night,
        suntime_daily_night,
        feature_forward_return_daily_schedule,
        feature_minute_daily_schedule,
        feature_daily_main_schedule,
        feature_umr_daily_schedule,
    ),
}


def schedules_for_profile(profile: str) -> tuple[ScheduleDefinition, ...]:
    # 未知 profile 直接报错，不回退到"全部调度"，避免误启用不该跑的调度。
    if profile not in PROFILE_SCHEDULES:
        raise ValueError(f"未知 QUANTAGENT_PROFILE={profile!r}，无法选择调度")
    return PROFILE_SCHEDULES[profile]


defs = Definitions(
    assets=[
        *WIND_SOURCE_ASSETS,
        std_trade_calendar,
        src_tushare_shibor,
        src_tushare_us_treasury_yield,
        src_macro_fred_observation_vintage,
        src_macro_gpr_daily,
        src_macro_jin10_economic_calendar,
        src_macro_wgc_gold_demand,
        src_jydb_c_ed_indicatormain,
        src_jydb_c_ed_macroindicatordata,
        src_jydb_c_in_indicatormain,
        src_jydb_c_in_indicatordatav,
        src_jydb_ed_moneysupply,
        src_jydb_qt_osindexquote,
        src_suntime_con_forecast_roll_idx,
        src_suntime_con_forecast_idx,
        src_suntime_rpt_earnings_adjust,
        src_suntime_fin_performance_forecast,
        src_suntime_fin_performance_express,
        src_suntime_fin_income_gen,
        src_suntime_con_forecast_roll_stk,
        src_suntime_con_forecast_stk,
        feature_pf_single_cutamp,
        feature_pf_single_tr_umr,
        src_eastmoney_minute,
        src_mysql_minute,
        *FEATURE_DAILY_ASSETS.values(),
        feature_daily_forward_return,
    ],
    jobs=[
        wind_source_refresh,
        wind_source_daily,
        wind_initial_backfill,
        tushare_daily,
        macro_daily,
        macro_wgc_weekly,
        jydb_daily,
        suntime_daily,
        feature_cutamp,
        feature_tr_umr,
        minprice_daily,
        feature_forward_return_daily,
        feature_minute_daily,
        feature_daily_main,
        feature_umr_daily,
    ],
    schedules=list(schedules_for_profile(get_settings().profile)),
    sensors=[run_failure_alert],
    resources=_resources(),
)
