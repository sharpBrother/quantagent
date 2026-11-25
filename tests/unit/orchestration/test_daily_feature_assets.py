"""日更资产与 cli 注册表一致：每个因子一个资产、deps 与就绪输入一一对应、每个资产只在一个作业里。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from orchestration.assets.daily_feature import FEATURE_DAILY_ASSETS, feature_daily_forward_return
from orchestration.definitions import defs

from quantagent.cli.daily_increment import FEATURE_INCREMENTS

if TYPE_CHECKING:
    from dagster import AssetsDefinition

# 就绪输入到 Dagster 资产键的对应。新增输入源时同步这里与 orchestration/assets/daily_feature.py。
_INPUT_KEY = {
    "ashareeodprices": "src_wind_ashareeodprices",
    "ashareeodderivativeindicator": "src_wind_ashareeodderivativeindicator",
    "asharemoneyflow": "src_wind_asharemoneyflow",
    "aindexeodprices": "src_wind_aindexeodprices",
    "minute": "src_eastmoney_minute",
}


def _key_names(asset_def: AssetsDefinition) -> set[str]:
    return {key.to_user_string() for key in asset_def.dependency_keys}


@pytest.mark.unit
def test_every_registered_factor_has_one_daily_asset_with_matching_inputs() -> None:
    by_feature = {
        asset_def.metadata_by_key[asset_def.key]["feature_id"]: asset_def
        for asset_def in FEATURE_DAILY_ASSETS.values()
    }
    assert set(by_feature) == {item.feature_id for item in FEATURE_INCREMENTS}
    for item in FEATURE_INCREMENTS:
        expected = {_INPUT_KEY[name] for name in item.inputs} | {"std_trade_calendar"}
        assert _key_names(by_feature[item.feature_id]) == expected, item.feature_id


@pytest.mark.unit
def test_forward_return_asset_reads_prices_and_calendar() -> None:
    assert _key_names(feature_daily_forward_return) == {
        "src_wind_ashareeodprices",
        "src_wind_ashareeodderivativeindicator",
        "std_trade_calendar",
    }


@pytest.mark.unit
def test_each_daily_asset_is_in_exactly_one_scheduled_job() -> None:
    job_names = (
        "feature_forward_return_daily",
        "feature_minute_daily",
        "feature_daily_main",
        "feature_umr_daily",
    )
    seen: dict[str, str] = {}
    for job_name in job_names:
        job = defs.resolve_job_def(job_name)
        for key in job.asset_layer.executable_asset_keys:
            name = key.path[-1]
            assert name not in seen, f"{name} 同时在 {seen[name]} 与 {job_name}"
            seen[name] = job_name
    expected = {asset_def.key.path[-1] for asset_def in FEATURE_DAILY_ASSETS.values()}
    expected.add(feature_daily_forward_return.key.path[-1])
    assert set(seen) == expected
