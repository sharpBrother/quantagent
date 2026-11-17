"""真实波幅 UMR 资产挂在日行情和标准日历之后，但不进入源刷新作业。"""

from __future__ import annotations

import pytest
from orchestration.assets.tr_umr import feature_pf_single_tr_umr
from orchestration.assets.wind import (
    src_wind_asharecalendar,
    src_wind_ashareeodprices,
    std_trade_calendar,
)
from orchestration.jobs.tr_umr import feature_tr_umr
from orchestration.jobs.wind import wind_source_refresh


@pytest.mark.unit
def test_tr_umr_depends_on_prices_and_calendar_and_stays_out_of_source_refresh() -> None:
    assert set(feature_pf_single_tr_umr.dependency_keys) == {
        src_wind_ashareeodprices.key,
        std_trade_calendar.key,
    }
    meta = feature_pf_single_tr_umr.metadata_by_key[feature_pf_single_tr_umr.key]
    assert meta["old_source_table"] == "wx2.dbo.stock_tr_umr"
    assert meta["old_loader"] == "alpha_factory.factor_loader.FactorLoader"
    assert meta["old_daily_refresh"] == "unchanged"
    catalog = [
        src_wind_asharecalendar,
        std_trade_calendar,
        src_wind_ashareeodprices,
        feature_pf_single_tr_umr,
    ]
    source_job = set(wind_source_refresh.selection.resolve(catalog))
    assert feature_pf_single_tr_umr.key not in source_job
    assert source_job == {
        src_wind_asharecalendar.key,
        std_trade_calendar.key,
        src_wind_ashareeodprices.key,
    }
    assert set(
        feature_tr_umr.selection.resolve([feature_pf_single_tr_umr, src_wind_ashareeodprices])
    ) == {feature_pf_single_tr_umr.key}
