"""聚源 P0/P1 可见性与 schema 契约：发布当天可见；货币供应取较早分支。"""

from __future__ import annotations

import pytest

from quantagent.contracts.loader import load_bundle


@pytest.mark.contracts
def test_jydb_p0_p1_contracts_are_declared() -> None:
    bundle = load_bundle()
    expected = {
        "src.jydb.c_ed_macroindicatordata",
        "src.jydb.c_in_indicatordatav",
        "src.jydb.ed_moneysupply",
    }
    assert expected <= set(bundle.visibilities)
    assert expected <= set(bundle.schemas)
    for dataset in expected - {"src.jydb.ed_moneysupply"}:
        visibility = bundle.visibilities[dataset]
        assert visibility.visibility.rule == "source_field"
        assert visibility.visibility.field == "InfoPublDate"
        assert visibility.visibility.date_only is True
        assert visibility.visibility.grade == "A"
        assert visibility.visibility.fallback is None
        assert visibility.pit_recoverable is True


@pytest.mark.contracts
def test_money_supply_uses_earliest_of_publish_and_next_month_15th() -> None:
    contract = load_bundle().visibilities["src.jydb.ed_moneysupply"]
    assert contract.visibility.fallback_mode == "earliest"
    assert contract.visibility.field == "InfoPublDate"
    assert contract.visibility.date_only is True
    fallback = contract.visibility.fallback
    assert fallback is not None
    assert fallback.rule == "fixed_lag"
    assert fallback.field == "EndDate"
    assert (fallback.lag_n, fallback.lag_unit) == (15, "calendar_day")
    assert fallback.grade == "B"


@pytest.mark.contracts
def test_catalog_tables_do_not_have_visibility() -> None:
    visibilities = load_bundle().visibilities
    assert "src.jydb.c_ed_indicatormain" not in visibilities
    assert "src.jydb.c_in_indicatormain" not in visibilities
