"""五日均值口径与四个因子的身份。"""

from __future__ import annotations

import pytest

from quantagent.features.library.minute.five_day import (
    DEFINITION_VERSION,
    SIGN,
    SPECS,
    WINDOW_OPEN_DAYS,
    window_mean,
)


@pytest.mark.unit
def test_window_mean_skips_missing_days() -> None:
    assert window_mean([1.0, None, 3.0, None, 5.0]) == pytest.approx(3.0)


@pytest.mark.unit
def test_window_mean_has_no_minimum_sample_count() -> None:
    assert window_mean([None, None, 2.5, None, None]) == 2.5


@pytest.mark.unit
def test_window_mean_all_missing_is_missing() -> None:
    assert window_mean([None] * WINDOW_OPEN_DAYS) is None


@pytest.mark.unit
def test_direction_is_negative() -> None:
    assert SIGN == -1.0


@pytest.mark.unit
def test_feature_ids_match_current20_and_are_unique() -> None:
    assert [spec.feature_id for spec in SPECS] == [
        "pf_single_corr_vrlag_5_mean_neg",
        "pf_single_real_kurt_5_mean_neg",
        "pf_single_ratio_realupvar_5_mean_neg",
        "pf_single_ratio_realdownvar_5_mean_neg",
    ]
    assert len({spec.param_hash for spec in SPECS}) == len(SPECS)
    assert DEFINITION_VERSION == "v1"
