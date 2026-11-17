"""现役真实波幅 UMR 的新资产。

旧入口是 Alpha Factory ``FactorLoader`` 的 ``performance_factor_single``：
从 ``wx2.dbo.stock_tr_umr`` 取 1 日 ``tr_umr``，方向 ``+1``。
这里改为读取本机日行情、中证全指收益和 SSE 开市日重算。不进入 Wind 源刷新作业，
也不关停旧仓日更。
"""

# 不使用 from __future__ import annotations：Dagster 导入时要解析 Config 注解。

from datetime import datetime

from dagster import Config, MaterializeResult, asset

from orchestration.assets.wind import src_wind_ashareeodprices, std_trade_calendar
from quantagent.features.library.price.tr_umr import DEFINITION_VERSION, FEATURE_ID, PARAM_HASH
from quantagent.platform.config import get_settings
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

_GROUP = "wind"


class TrUmrMaterializeConfig(Config):
    start: str
    end: str
    codes: str
    as_of: str


def _ymd(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


@asset(
    group_name=_GROUP,
    deps=[src_wind_ashareeodprices, std_trade_calendar],
    metadata={
        "reads": "src.wind.ashareeodprices,src.wind.aindexeodprices,std.trade_calendar",
        "feature_id": FEATURE_ID,
        "definition_version": DEFINITION_VERSION,
        "param_hash": PARAM_HASH,
        "old_source_table": "wx2.dbo.stock_tr_umr",
        "old_loader": "alpha_factory.factor_loader.FactorLoader",
        "old_daily_refresh": "unchanged",
    },
)
def feature_pf_single_tr_umr(config: TrUmrMaterializeConfig) -> MaterializeResult[None]:
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    wind_codes = tuple(part.strip() for part in config.codes.split(",") if part.strip())
    from quantagent.cli.tr_umr_materialize import (
        materialize_tr_umr,
    )

    row_count, digest = materialize_tr_umr(
        settings=settings,
        paths=paths,
        start=_ymd(config.start).date(),
        end=_ymd(config.end).date(),
        wind_codes=wind_codes,
        as_of=_ymd(config.as_of).date(),
    )
    return MaterializeResult(
        metadata={
            "row_count": row_count,
            "digest": digest,
            "as_of": config.as_of,
            "feature_id": FEATURE_ID,
        }
    )
