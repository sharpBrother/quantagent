"""现役切段振幅的新资产。

旧入口是 Alpha Factory ``FactorLoader`` 的 ``performance_factor_single``：
从 ``wx2.dbo.stock_cutamp`` 取 1 日 ``cutamp``，再乘 ``direction=-1``。
这里改为读取本机日行情重算。不进入 Wind 源刷新作业，也不关停旧仓日更。
"""

from datetime import datetime

from dagster import Config, MaterializeResult, asset

from orchestration.assets.wind import src_wind_ashareeodprices
from quantagent.features.library.price.cutamp import DEFINITION_VERSION, FEATURE_ID, PARAM_HASH
from quantagent.platform.config import get_settings
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

_GROUP = "wind"


class CutampMaterializeConfig(Config):
    start: str
    end: str
    codes: str
    as_of: str


def _ymd(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


@asset(
    group_name=_GROUP,
    deps=[src_wind_ashareeodprices],
    metadata={
        "reads": "src.wind.ashareeodprices",
        "feature_id": FEATURE_ID,
        "definition_version": DEFINITION_VERSION,
        "param_hash": PARAM_HASH,
        "old_source_table": "wx2.dbo.stock_cutamp",
        "old_loader": "alpha_factory.factor_loader.FactorLoader",
    },
)
def feature_pf_single_cutamp(config: CutampMaterializeConfig) -> MaterializeResult[None]:
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    wind_codes = tuple(part.strip() for part in config.codes.split(",") if part.strip())
    from quantagent.cli.cutamp_materialize import (
        materialize_cutamp,
    )

    row_count, digest = materialize_cutamp(
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
            "pit_grade": "A",
        }
    )
