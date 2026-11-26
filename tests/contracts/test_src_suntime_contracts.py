"""朝阳永续 P0 可见性：一致预期快照当天收盘后可见；调整表不写契约。"""

from __future__ import annotations

import pytest

from quantagent.contracts.loader import load_bundle


@pytest.mark.contracts
def test_suntime_consensus_contracts_are_declared() -> None:
    bundle = load_bundle()
    expected = {
        "src.suntime.con_forecast_stk",
        "src.suntime.con_forecast_roll_stk",
        "src.suntime.con_forecast_idx",
        "src.suntime.con_forecast_roll_idx",
    }
    assert expected <= set(bundle.visibilities)
    assert expected <= set(bundle.schemas)
    for dataset in expected:
        schema = bundle.schemas[dataset]
        visibility = bundle.visibilities[dataset]
        assert schema.temporal_kind == "snapshot"
        assert schema.keys == ["id"]
        assert visibility.temporal_kind == "snapshot"
        assert visibility.visibility.rule == "source_field"
        assert visibility.visibility.field == "con_date"
        assert visibility.visibility.strict is False
        assert visibility.visibility.grade == "A"
        assert visibility.pit_recoverable is True
    # 个股年度表的 con_date 是 timestamp，必须按日期比较；其余三张是 date。
    assert bundle.visibilities["src.suntime.con_forecast_stk"].visibility.date_only is True
    assert bundle.visibilities["src.suntime.con_forecast_roll_stk"].visibility.date_only is False


@pytest.mark.contracts
def test_mirror_only_tables_have_no_visibility() -> None:
    # 只建镜像：没有契约，引擎拒绝对它们做 PIT 查询。
    visibilities = load_bundle().visibilities
    assert "src.suntime.rpt_earnings_adjust" not in visibilities
    assert "src.suntime.con_forecast_stk_ttm" not in visibilities
