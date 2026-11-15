"""切段振幅资产挂在日行情之后，但不进入源刷新作业。"""

from __future__ import annotations

import pytest
from orchestration.assets.cutamp import feature_pf_single_cutamp
from orchestration.assets.wind import (
    src_wind_asharecalendar,
    src_wind_ashareeodprices,
    std_trade_calendar,
)
from orchestration.jobs.cutamp import feature_cutamp
from orchestration.jobs.wind import wind_source_refresh


@pytest.mark.unit
def test_cutamp_depends_on_prices_and_stays_out_of_source_refresh() -> None:
    assert list(feature_pf_single_cutamp.dependency_keys) == [src_wind_ashareeodprices.key]
    source_job = set(
        wind_source_refresh.selection.resolve(
            [src_wind_asharecalendar, std_trade_calendar, src_wind_ashareeodprices]
        )
    )
    assert feature_pf_single_cutamp.key not in source_job
    assert set(feature_cutamp.selection.resolve([feature_pf_single_cutamp])) == {
        feature_pf_single_cutamp.key
    }
