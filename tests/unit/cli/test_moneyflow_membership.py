"""资金流物化的股票池按截面日 all_a 取，不用 end 日成员回填整个区间。

区间中途退出 all_a 的股票，在退出前的截面日仍要产出；退出后的截面日不产出。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from quantagent.cli.moneyflow_materialize import keep_rows_in_membership, union_codes
from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.index_returns.types import IndexReturn
from quantagent.domain.money_flow.types import MoneyFlow
from quantagent.domain.prices.types import DailyPrice
from quantagent.features.library.money_flow import moneyflowh
from quantagent.features.panel.money_flow import build_money_flow_factor_values


def _contract(dataset: str) -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": dataset,
            "doc_ref": "docs/contracts/src-wind-first-batch.md",
            "temporal_kind": "point_event",
            "event_field": "TRADE_DT",
            "visibility": {
                "rule": "same_day_close",
                "grade": "A",
                "rationale": "单元测试用的可见性规则说明，长度足够通过契约校验",
            },
            "pit_recoverable": True,
        }
    )


def _opens(count: int) -> tuple[date, ...]:
    start = date(2024, 3, 1)
    return tuple(start + timedelta(days=offset) for offset in range(count))


def _price(day: date, code: str) -> DailyPrice:
    return DailyPrice(
        trade_dt=day,
        wind_code=code,
        open=Decimal("10"),
        high=Decimal("10"),
        low=Decimal("10"),
        close=Decimal("10"),
        volume=Decimal("1"),
        amount=Decimal("1000"),
        pct_change=Decimal("0"),
        adj_close=Decimal("10"),
        adj_high=Decimal("10"),
        adj_low=Decimal("10"),
        adj_preclose=Decimal("10"),
    )


def _flow(day: date, code: str) -> MoneyFlow:
    one = Decimal("1")
    return MoneyFlow(
        trade_dt=day,
        wind_code=code,
        buy_value_small_order_act=one,
        buy_value_med_order_act=one,
        buy_value_large_order_act=one,
        sell_value_med_order_act=one,
        sell_value_large_order_act=one,
        value_diff_small_trader=one,
        value_diff_med_trader=one,
        value_diff_large_trader=one,
        value_diff_institute=one,
    )


@pytest.mark.unit
def test_union_codes_is_sorted_and_deduplicated_across_days() -> None:
    members = {
        date(2024, 3, 1): frozenset({"600000.SH", "000001.SZ"}),
        date(2024, 3, 4): frozenset({"000001.SZ", "300001.SZ"}),
    }
    assert union_codes(members) == ("000001.SZ", "300001.SZ", "600000.SH")
    assert union_codes({}) == ()


@pytest.mark.unit
def test_keep_rows_uses_membership_of_each_event_day() -> None:
    days = _opens(30)
    rows = build_money_flow_factor_values(
        [_price(day, "000001.SZ") for day in days],
        [_flow(day, "000001.SZ") for day in days],
        [
            IndexReturn(trade_dt=day, wind_code="000985.CSI", pct_change=Decimal("0"))
            for day in days
        ],
        days,
        price_contract=_contract("src.wind.ashareeodprices"),
        money_flow_contract=_contract("src.wind.asharemoneyflow"),
        index_contract=_contract("src.wind.aindexeodprices"),
        start=days[0],
        end=days[-1],
        computed_at=datetime(2026, 11, 24),
        run_id="unit",
    )
    assert rows
    # 000001.SZ 只在第 20 个截面日之前属于 all_a。之后的截面日即使有行也不产出。
    members = {
        day: frozenset({"000001.SZ"}) if index < 20 else frozenset()
        for index, day in enumerate(days)
    }
    kept = keep_rows_in_membership(rows, members)
    assert kept == tuple(row for row in rows if row.event_dt < days[20])


@pytest.mark.unit
def test_stock_leaving_all_a_mid_range_still_produces_before_exit() -> None:
    days = _opens(30)
    exit_index = 25
    # X 在第 25 个截面日之前属于 all_a，之后仍有行情，但不再是成员。
    # Y 全程属于 all_a。
    prices = [_price(day, "000002.SZ") for day in days] + [_price(day, "000001.SZ") for day in days]
    flows = [_flow(day, "000002.SZ") for day in days] + [_flow(day, "000001.SZ") for day in days]
    indexes = [
        IndexReturn(trade_dt=day, wind_code="000985.CSI", pct_change=Decimal("0")) for day in days
    ]
    members_by_day = {
        day: frozenset({"000001.SZ", "000002.SZ"})
        if index <= exit_index
        else frozenset({"000001.SZ"})
        for index, day in enumerate(days)
    }
    # 读取范围取并集，因此 X 的行情与资金流都会被读入。
    assert union_codes(members_by_day) == ("000001.SZ", "000002.SZ")
    rows = build_money_flow_factor_values(
        prices,
        flows,
        indexes,
        days,
        price_contract=_contract("src.wind.ashareeodprices"),
        money_flow_contract=_contract("src.wind.asharemoneyflow"),
        index_contract=_contract("src.wind.aindexeodprices"),
        start=days[0],
        end=days[-1],
        computed_at=datetime(2026, 11, 24),
        run_id="unit",
    )
    kept = keep_rows_in_membership(rows, members_by_day)
    x_events = sorted(
        row.event_dt
        for row in kept
        if row.asset_id == "000002.SZ" and row.feature_id == moneyflowh.FEATURE_ID
    )
    # 窗口需要 20 行，最早产出在第 20 个开市日。退出前的截面日都要有值，退出后没有。
    assert x_events == list(days[19 : exit_index + 1])
    y_events = sorted(
        row.event_dt
        for row in kept
        if row.asset_id == "000001.SZ" and row.feature_id == moneyflowh.FEATURE_ID
    )
    assert y_events == list(days[19:])
