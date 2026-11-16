"""Dagster 入口。本地查看图：``dagster dev -m orchestration.definitions``。

运行存储由 ``DAGSTER_HOME`` 里的 ``dagster.yaml`` 决定，不在导入时连接控制库。
模板是 ``orchestration/dagster.yaml``：``search_path=ops``，关闭自建表。
"""

from __future__ import annotations

from dagster import Definitions

from orchestration.assets.cutamp import feature_pf_single_cutamp
from orchestration.assets.wind import (
    src_wind_asharecalendar,
    src_wind_ashareeodprices,
    std_trade_calendar,
)
from orchestration.jobs.cutamp import feature_cutamp
from orchestration.jobs.wind import wind_source_refresh
from orchestration.resources.wind import TradeCalendarResource, WindIngestResource
from quantagent.platform.config import get_settings
from quantagent.platform.storage import detect_repo_root, resolve_var_paths


def _resources() -> dict[str, WindIngestResource | TradeCalendarResource]:
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    return {
        "wind_ingest": WindIngestResource(settings=settings, paths=paths),
        "trade_calendar": TradeCalendarResource(settings=settings, paths=paths),
    }


defs = Definitions(
    assets=[
        src_wind_asharecalendar,
        std_trade_calendar,
        src_wind_ashareeodprices,
        feature_pf_single_cutamp,
    ],
    jobs=[wind_source_refresh, feature_cutamp],
    resources=_resources(),
)
