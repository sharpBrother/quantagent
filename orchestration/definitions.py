"""Dagster 入口。本地查看图：``dagster dev -m orchestration.definitions``。

运行存储由 ``DAGSTER_HOME`` 里的 ``dagster.yaml`` 决定，不在导入时连接控制库。
模板是 ``orchestration/dagster.yaml``：``search_path=ops``，关闭自建表。
"""

from __future__ import annotations

from dagster import Definitions, ScheduleDefinition

from orchestration.assets.cutamp import feature_pf_single_cutamp
from orchestration.assets.macro import (
    src_macro_fred_observation_vintage,
    src_macro_gpr_daily,
    src_macro_wgc_gold_demand,
)
from orchestration.assets.tr_umr import feature_pf_single_tr_umr
from orchestration.assets.tushare import src_tushare_shibor, src_tushare_us_treasury_yield
from orchestration.assets.wind import WIND_SOURCE_ASSETS, std_trade_calendar
from orchestration.jobs.cutamp import feature_cutamp
from orchestration.jobs.macro import macro_daily, macro_wgc_weekly
from orchestration.jobs.tr_umr import feature_tr_umr
from orchestration.jobs.tushare import tushare_daily
from orchestration.jobs.wind import wind_source_daily, wind_source_refresh
from orchestration.resources.wind import TradeCalendarResource, WindIngestResource
from orchestration.schedules.macro import macro_daily_morning, macro_wgc_sunday
from orchestration.schedules.tushare import tushare_daily_evening
from orchestration.schedules.wind import wind_source_daily_close, wind_source_daily_morning
from quantagent.platform.config import get_settings
from quantagent.platform.storage import detect_repo_root, resolve_var_paths


def _resources() -> dict[str, WindIngestResource | TradeCalendarResource]:
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    return {
        "wind_ingest": WindIngestResource(settings=settings, paths=paths),
        "trade_calendar": TradeCalendarResource(settings=settings, paths=paths),
    }


# 调度按机器 profile 注册。两台机器跑同一份代码，资产与作业两边都注册（UI 里都能看到），
# 只有调度按 profile 取舍，否则不该跑的调度每天都会失败。
# 本映射与 ``quantagent.ingest.writers.tables.PROFILE_WRITABLE_SCHEMAS`` 一一对应：
# office 只写 src_wind，local 只写 src_tushare / src_macro。改一边必须同时改另一边，
# ``tests/unit/orchestration/test_definitions_profile.py`` 会校验两者是否一致。
PROFILE_SCHEDULES: dict[str, tuple[ScheduleDefinition, ...]] = {
    "office": (wind_source_daily_close, wind_source_daily_morning),
    "local": (tushare_daily_evening, macro_daily_morning, macro_wgc_sunday),
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
        src_macro_wgc_gold_demand,
        feature_pf_single_cutamp,
        feature_pf_single_tr_umr,
    ],
    jobs=[
        wind_source_refresh,
        wind_source_daily,
        tushare_daily,
        macro_daily,
        macro_wgc_weekly,
        feature_cutamp,
        feature_tr_umr,
    ],
    schedules=list(schedules_for_profile(get_settings().profile)),
    resources=_resources(),
)
