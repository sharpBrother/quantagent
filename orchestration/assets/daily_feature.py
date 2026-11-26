"""日更增量资产：每个因子一个资产，前瞻收益一个资产（内部按 horizon 串行）。

资产只调用 ``quantagent.cli.daily_increment``，业务规则不在这里。``as_of`` 由调度给出（执行机当地日期），
资产里不取系统时间，便于重跑与测试。这里的因子清单与 ``quantagent.cli.daily_increment.FEATURE_INCREMENTS``
必须一致，``tests/unit/orchestration/test_daily_feature_assets.py`` 校验这一点。

模块导入时不加载 pandas / pyarrow / duckdb：业务实现都在资产函数内延迟导入。
"""

# 不使用 from __future__ import annotations：Dagster 导入时要解析 Config 注解。
from datetime import date, datetime

from dagster import AssetsDefinition, Config, MaterializeResult, asset

from orchestration.assets.minprice import src_eastmoney_minute
from orchestration.assets.suntime import src_suntime_rpt_earnings_adjust
from orchestration.assets.wind import WIND_SOURCE_ASSETS, std_trade_calendar
from quantagent.platform.config import get_settings
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

_GROUP = "feature_daily"


class DailyIncrementConfig(Config):
    as_of: str


_WIND_BY_NAME = {asset_def.key.to_user_string(): asset_def for asset_def in WIND_SOURCE_ASSETS}

_INPUT_DEPS: dict[str, AssetsDefinition] = {
    "ashareeodprices": _WIND_BY_NAME["src_wind_ashareeodprices"],
    "ashareeodderivativeindicator": _WIND_BY_NAME["src_wind_ashareeodderivativeindicator"],
    "asharemoneyflow": _WIND_BY_NAME["src_wind_asharemoneyflow"],
    "aindexeodprices": _WIND_BY_NAME["src_wind_aindexeodprices"],
    "minute": src_eastmoney_minute,
}

# did_ratio 的财报血缘输入。它们是事件驱动、按 ANN_DT 截止，不参与行数就绪判定，
# 但必须在 deps 里：日更应在财报采集之后跑，否则读到的还是昨天的财报。
_DID_RATIO_FUNDAMENTAL_DEPS: tuple[AssetsDefinition, ...] = (
    _WIND_BY_NAME["src_wind_asharedividend"],
    _WIND_BY_NAME["src_wind_ashareincome"],
    _WIND_BY_NAME["src_wind_asharefinancialindicator"],
)

# nap_adj_ratio 的朝阳永续血缘输入。调整行是事件驱动、按 entrytime 截止，不参与行数就绪判定，
# 但必须在 deps 里：日更应在调整行采集之后跑，否则读到的还是昨天的数据。
_NAP_ADJ_SUNTIME_DEPS: tuple[AssetsDefinition, ...] = (src_suntime_rpt_earnings_adjust,)

# (资产名, feature_id, 输入)。输入决定 deps 与就绪判定，两处取值相同。
# 凡按 all_a 取股票的因子，衍生指标表也是输入（all_a 成员由当日衍生指标代码决定）。
_FEATURES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "feature_daily_cutamp",
        "pf_single_cutamp_1_mean_neg",
        ("ashareeodprices", "ashareeodderivativeindicator"),
    ),
    (
        "feature_daily_mif",
        "pf_single_mif_1_mean_neg",
        ("ashareeodprices", "ashareeodderivativeindicator"),
    ),
    (
        "feature_daily_moneyflowh",
        "pf_single_moneyflowh_1_mean_neg",
        ("ashareeodprices", "asharemoneyflow", "ashareeodderivativeindicator"),
    ),
    (
        "feature_daily_actlargemedcut",
        "pf_single_actlargemedcut_1_mean_pos",
        ("ashareeodprices", "asharemoneyflow", "ashareeodderivativeindicator"),
    ),
    (
        "feature_daily_abso_umr",
        "pf_single_abso_umr_1_mean_pos",
        ("ashareeodprices", "asharemoneyflow", "aindexeodprices", "ashareeodderivativeindicator"),
    ),
    (
        "feature_daily_tr_umr",
        "pf_single_tr_umr_1_mean_pos",
        ("ashareeodprices", "aindexeodprices", "ashareeodderivativeindicator"),
    ),
    (
        "feature_daily_corr_vrlag",
        "pf_single_corr_vrlag_5_mean_neg",
        ("minute", "ashareeodderivativeindicator"),
    ),
    (
        "feature_daily_real_kurt",
        "pf_single_real_kurt_5_mean_neg",
        ("minute", "ashareeodderivativeindicator"),
    ),
    (
        "feature_daily_ratio_realupvar",
        "pf_single_ratio_realupvar_5_mean_neg",
        ("minute", "ashareeodderivativeindicator"),
    ),
    (
        "feature_daily_ratio_realdownvar",
        "pf_single_ratio_realdownvar_5_mean_neg",
        ("minute", "ashareeodderivativeindicator"),
    ),
    (
        "feature_daily_corr_vrlaglarge",
        "pf_single_corr_vrlaglarge_5_mean_neg",
        ("minute", "ashareeodprices", "ashareeodderivativeindicator"),
    ),
    (
        "feature_daily_core_up",
        "pf_single_core_up_20_mean_pos_neut_pxret21",
        ("minute", "ashareeodprices", "ashareeodderivativeindicator"),
    ),
    (
        "feature_daily_core_down",
        "pf_single_core_down_20_mean_neg_neut_pxret21",
        ("minute", "ashareeodprices", "ashareeodderivativeindicator"),
    ),
    (
        "feature_daily_did_ratio",
        "pf_single_stock_did_ratio_did_ratio_realized_1_1_mean_pos",
        ("ashareeodderivativeindicator",),
    ),
    (
        "feature_daily_nap_adj_ratio",
        "pf_single_nap_adj_ratio_1_mean_pos",
        ("ashareeodderivativeindicator",),
    ),
)


def _parse_day(value: str) -> date:
    """调度给出的 as_of 必须是 YYYY-MM-DD，否则报错，不猜测日期。"""
    return datetime.strptime(value, "%Y-%m-%d").date()


def _feature_asset(name: str, feature_id: str, inputs: tuple[str, ...]) -> AssetsDefinition:
    deps = [std_trade_calendar, *(_INPUT_DEPS[item] for item in inputs)]
    # did_ratio 额外依赖财报资产：血缘要求在财报采集之后跑，但不参与行数就绪判定。
    if name == "feature_daily_did_ratio":
        deps = [*deps, *_DID_RATIO_FUNDAMENTAL_DEPS]
    # nap_adj_ratio 额外依赖朝阳永续调整行采集资产，同理不参与行数就绪判定。
    if name == "feature_daily_nap_adj_ratio":
        deps = [*deps, *_NAP_ADJ_SUNTIME_DEPS]

    @asset(
        name=name,
        group_name=_GROUP,
        deps=deps,
        metadata={
            "reads": ",".join(inputs),
            "feature_id": feature_id,
            "mode": "incremental",
        },
    )
    def _materialize(config: DailyIncrementConfig) -> MaterializeResult[None]:
        from quantagent.cli.daily_increment import run_feature_increment

        settings = get_settings()
        paths = resolve_var_paths(settings, repo_root=detect_repo_root())
        result = run_feature_increment(
            settings=settings,
            paths=paths,
            feature_id=feature_id,
            as_of=_parse_day(config.as_of),
        )
        return MaterializeResult(metadata=result.metadata())

    return _materialize


FEATURE_DAILY_ASSETS: dict[str, AssetsDefinition] = {
    name: _feature_asset(name, feature_id, inputs) for name, feature_id, inputs in _FEATURES
}


@asset(
    name="feature_daily_forward_return",
    group_name=_GROUP,
    deps=[
        std_trade_calendar,
        _INPUT_DEPS["ashareeodprices"],
        _INPUT_DEPS["ashareeodderivativeindicator"],
    ],
    metadata={
        "reads": "src.wind.ashareeodprices,src.wind.ashareeodderivativeindicator,std.trade_calendar",
        "dataset": "mart.forward_return",
        "mode": "incremental",
    },
)
def feature_daily_forward_return(config: DailyIncrementConfig) -> MaterializeResult[None]:
    """四个 horizon 串行。每个 horizon 各自从 lake 的最大信号日之后开始。"""
    from quantagent.cli.daily_increment import run_forward_return_increment
    from quantagent.domain.forward_return import HORIZONS

    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    as_of = _parse_day(config.as_of)
    metadata: dict[str, str | int] = {}
    for horizon in HORIZONS:
        result = run_forward_return_increment(
            settings=settings, paths=paths, horizon=horizon, as_of=as_of
        )
        for key, value in result.metadata().items():
            metadata[f"{horizon}_{key}"] = value
    return MaterializeResult(metadata=metadata)
