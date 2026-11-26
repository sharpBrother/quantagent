"""朝阳永续可见性：一致预期快照当天收盘后可见；盈利预测调整按入库时间 entrytime 可见。"""

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
def test_rpt_earnings_adjust_visibility_is_entrytime() -> None:
    # nap_adj_ratio 可见性：负责人 2026-11-26 裁定，事件时间是研报日期 current_create_date，
    # 可见截止用入库时间 entrytime（解决旧仓按研报日期过滤的前视），grade A、按日期比较。
    bundle = load_bundle()
    visibility = bundle.visibilities["src.suntime.rpt_earnings_adjust"]
    assert visibility.temporal_kind == "point_event"
    assert visibility.event_field == "current_create_date"
    assert visibility.visibility.rule == "source_field"
    assert visibility.visibility.field == "entrytime"
    assert visibility.visibility.date_only is True
    assert visibility.visibility.grade == "A"
    assert visibility.pit_recoverable is True
    schema = bundle.schemas["src.suntime.rpt_earnings_adjust"]
    assert schema.temporal_kind == "point_event"
    assert schema.keys == ["id"]
    assert schema.event_field == "current_create_date"


@pytest.mark.contracts
def test_derived_only_tables_have_no_visibility() -> None:
    # con_forecast_stk_ttm 是旧仓派生表、不作源镜像同步，没有契约，引擎拒绝对它做 PIT 查询。
    visibilities = load_bundle().visibilities
    assert "src.suntime.con_forecast_stk_ttm" not in visibilities
