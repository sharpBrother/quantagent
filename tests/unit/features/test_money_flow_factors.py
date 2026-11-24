"""资金流三因子的单元测试：窗口、缺失、并列与 UMR 数值。不读存储。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.errors import FeatureLookupError
from quantagent.domain.index_returns.types import IndexReturn
from quantagent.domain.money_flow.types import MoneyFlow
from quantagent.domain.prices.types import DailyPrice
from quantagent.features.library.money_flow import abso_umr, actlargemedcut, moneyflowh
from quantagent.features.panel.money_flow import build_money_flow_factor_values
from quantagent.features.window import last_n_trading_days


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


PRICE_CONTRACT = _contract("src.wind.ashareeodprices")
FLOW_CONTRACT = _contract("src.wind.asharemoneyflow")
INDEX_CONTRACT = _contract("src.wind.aindexeodprices")


def _opens(count: int, last: date) -> tuple[date, ...]:
    days = [last - timedelta(days=offset) for offset in range(count * 2)]
    return tuple(sorted(days[:count]))


def _price(
    day: date, code: str, *, adj_close: str = "10", preclose: str = "10", pct: str = "0"
) -> DailyPrice:
    return DailyPrice(
        trade_dt=day,
        wind_code=code,
        open=Decimal("10"),
        high=Decimal("10"),
        low=Decimal("10"),
        close=Decimal(adj_close),
        volume=Decimal("1"),
        amount=Decimal("1000"),
        pct_change=Decimal(pct),
        adj_close=Decimal(adj_close),
        adj_high=Decimal("10"),
        adj_low=Decimal("10"),
        adj_preclose=Decimal(preclose),
    )


def _flow(day: date, code: str, *, diff: str = "1", act: str = "1") -> MoneyFlow:
    return MoneyFlow(
        trade_dt=day,
        wind_code=code,
        buy_value_small_order_act=Decimal(act),
        buy_value_med_order_act=Decimal(act),
        buy_value_large_order_act=Decimal(act),
        sell_value_med_order_act=Decimal(act),
        sell_value_large_order_act=Decimal(act),
        value_diff_small_trader=Decimal(diff),
        value_diff_med_trader=Decimal(diff),
        value_diff_large_trader=Decimal(diff),
        value_diff_institute=Decimal(diff),
    )


def _index(day: date, *, pct: str = "0") -> IndexReturn:
    return IndexReturn(trade_dt=day, wind_code="000985.CSI", pct_change=Decimal(pct))


# ---------------------------------------------------------------- moneyflowh


@pytest.mark.unit
def test_moneyflowh_equal_flows_give_half_and_negative_value() -> None:
    days = _opens(20, date(2024, 3, 1))
    window = tuple(_price(day, "000001.SZ") for day in days)
    flows = {day: _flow(day, "000001.SZ") for day in days}
    got = moneyflowh.moneyflowh_value(
        window, flows, price_contract=PRICE_CONTRACT, money_flow_contract=FLOW_CONTRACT
    )
    assert got is not None
    # 四类绝对值之和各为 20，(机构 + 散户) / 总和 = 40 / 80。方向 -1。
    assert got.raw == Decimal("0.5")
    assert got.value == Decimal("-0.5")
    assert got.event_dt == days[-1]
    assert got.pit_grade == "A"


@pytest.mark.unit
def test_moneyflowh_missing_flow_inside_window_gives_no_value() -> None:
    days = _opens(20, date(2024, 3, 1))
    window = tuple(_price(day, "000001.SZ") for day in days)
    flows = {day: _flow(day, "000001.SZ") for day in days if day != days[5]}
    assert (
        moneyflowh.moneyflowh_value(
            window, flows, price_contract=PRICE_CONTRACT, money_flow_contract=FLOW_CONTRACT
        )
        is None
    )


@pytest.mark.unit
def test_moneyflowh_zero_denominator_and_short_window_give_no_value() -> None:
    days = _opens(20, date(2024, 3, 1))
    window = tuple(_price(day, "000001.SZ") for day in days)
    zero = {day: _flow(day, "000001.SZ", diff="0") for day in days}
    assert (
        moneyflowh.moneyflowh_value(
            window, zero, price_contract=PRICE_CONTRACT, money_flow_contract=FLOW_CONTRACT
        )
        is None
    )
    short = tuple(_price(day, "000001.SZ") for day in days[1:])
    assert (
        moneyflowh.moneyflowh_value(
            short,
            {day: _flow(day, "000001.SZ") for day in days},
            price_contract=PRICE_CONTRACT,
            money_flow_contract=FLOW_CONTRACT,
        )
        is None
    )


# ------------------------------------------------------------ actlargemedcut


@pytest.mark.unit
def test_actlargemedcut_takes_top_fifteen_percent_by_ratio_with_legacy_ties() -> None:
    days = _opens(20, date(2024, 3, 1))
    # ratio 只取三个值，制造大量并列。act 逐日不同，便于看出选了哪几天。
    ratio_steps = [0, 1, 1, 2, 0, 1, 2, 2, 0, 1, 1, 0, 2, 1, 0, 2, 1, 1, 0, 2]
    window: list[DailyPrice] = []
    flows: dict[date, MoneyFlow] = {}
    for index, day in enumerate(days):
        # adj_close / adj_preclose - 1 = step / 100，即 ratio = step。
        close = Decimal(100 + ratio_steps[index])
        window.append(_price(day, "000001.SZ", adj_close=str(close), preclose="100"))
        big = Decimal(index + 1)
        flows[day] = MoneyFlow(
            trade_dt=day,
            wind_code="000001.SZ",
            buy_value_small_order_act=None,
            buy_value_med_order_act=Decimal(1),
            buy_value_large_order_act=big,
            sell_value_med_order_act=Decimal(1),
            sell_value_large_order_act=Decimal(1),
            value_diff_small_trader=None,
            value_diff_med_trader=None,
            value_diff_large_trader=None,
            value_diff_institute=None,
        )
    got = actlargemedcut.actlargemedcut_value(
        tuple(window), flows, price_contract=PRICE_CONTRACT, money_flow_contract=FLOW_CONTRACT
    )
    assert got is not None
    # 期望值用 pandas 的降序排序独立算出，并列顺序由它决定。
    ratios = pd.Series([float(step) for step in ratio_steps], dtype="float64")
    acts = [
        (Decimal(index + 1) - 1 + 1 - 1) / (Decimal(index + 1) + 1 + 1 + 1) for index in range(20)
    ]
    top = ratios.sort_values(ascending=False).index[: int(0.15 * 20)]
    expected = sum((acts[i] for i in top), Decimal(0)) / len(top)
    assert got.raw == expected
    assert got.pit_grade == "A"


@pytest.mark.unit
def test_actlargemedcut_zero_total_or_missing_price_gives_no_value() -> None:
    days = _opens(20, date(2024, 3, 1))
    window = tuple(_price(day, "000001.SZ") for day in days)
    zero = {day: _flow(day, "000001.SZ", act="0") for day in days}
    assert (
        actlargemedcut.actlargemedcut_value(
            window, zero, price_contract=PRICE_CONTRACT, money_flow_contract=FLOW_CONTRACT
        )
        is None
    )
    no_preclose = list(window)
    no_preclose[3] = DailyPrice(
        trade_dt=days[3],
        wind_code="000001.SZ",
        open=None,
        high=None,
        low=None,
        close=None,
        volume=None,
        amount=None,
        pct_change=None,
        adj_close=Decimal("10"),
        adj_preclose=None,
    )
    assert (
        actlargemedcut.actlargemedcut_value(
            tuple(no_preclose),
            {day: _flow(day, "000001.SZ") for day in days},
            price_contract=PRICE_CONTRACT,
            money_flow_contract=FLOW_CONTRACT,
        )
        is None
    )


# ------------------------------------------------------------------- abso_umr


def _reference_umr(abso: list[float], excess: list[float]) -> float:
    """独立的 pandas 参考实现：与旧仓 _rolling_risk_coef / _calc_umr 的公式一致。"""
    series = pd.Series(abso, dtype="float64")
    coef = (series.rolling(10, min_periods=10).mean() - series).tail(60)
    excess_s = pd.Series(excess, dtype="float64").tail(60)
    exp_wt = np.asarray([0.5 ** (1 / 30)] * 60) ** np.arange(60)
    weights = exp_wt[::-1] / np.sum(exp_wt)
    return float(np.sum(coef.to_numpy() * excess_s.to_numpy() * weights))


@pytest.mark.unit
def test_abso_umr_matches_pandas_reference_on_complete_window() -> None:
    opens = _opens(69, date(2024, 6, 28))
    rng = np.random.default_rng(7)
    prices = []
    flows = []
    indexes = []
    abso: list[float] = []
    excess: list[float] = []
    for day in opens:
        amount = Decimal(str(round(float(rng.uniform(1e5, 9e5)), 4)))
        act = Decimal(str(round(float(rng.uniform(1e4, 9e4)), 4)))
        pct = Decimal(str(round(float(rng.uniform(-3, 3)), 4)))
        bench = Decimal(str(round(float(rng.uniform(-2, 2)), 4)))
        prices.append(
            DailyPrice(
                trade_dt=day,
                wind_code="000001.SZ",
                open=None,
                high=None,
                low=None,
                close=None,
                volume=None,
                amount=amount,
                pct_change=pct,
                adj_high=Decimal("10"),
                adj_low=Decimal("9"),
                adj_preclose=Decimal("9.5"),
            )
        )
        flows.append(
            MoneyFlow(
                trade_dt=day,
                wind_code="000001.SZ",
                buy_value_small_order_act=act,
                buy_value_med_order_act=None,
                buy_value_large_order_act=None,
                sell_value_med_order_act=None,
                sell_value_large_order_act=None,
                value_diff_small_trader=None,
                value_diff_med_trader=None,
                value_diff_large_trader=None,
                value_diff_institute=None,
            )
        )
        indexes.append(_index(day, pct=str(bench)))
        abso.append(-(float(act) / float(amount)))
        excess.append(float(pct) - float(bench))
    got = abso_umr.abso_umr_value(
        opens,
        prices,
        flows,
        indexes,
        price_contract=PRICE_CONTRACT,
        money_flow_contract=FLOW_CONTRACT,
        index_contract=INDEX_CONTRACT,
    )
    assert got is not None
    assert got.event_dt == opens[-1]
    assert got.value == pytest.approx(_reference_umr(abso, excess), rel=1e-12, abs=1e-15)


@pytest.mark.unit
def test_abso_umr_missing_small_order_inside_window_gives_no_value() -> None:
    opens = _opens(69, date(2024, 6, 28))
    prices = [_price(day, "000001.SZ", pct="1") for day in opens]
    flows = [_flow(day, "000001.SZ", act="100") for day in opens]
    # 第 20 日的小单主动买入缺失，它落在最后 60 个风险系数的计算范围内。
    flows[20] = MoneyFlow(
        trade_dt=opens[20],
        wind_code="000001.SZ",
        buy_value_small_order_act=None,
        buy_value_med_order_act=None,
        buy_value_large_order_act=None,
        sell_value_med_order_act=None,
        sell_value_large_order_act=None,
        value_diff_small_trader=None,
        value_diff_med_trader=None,
        value_diff_large_trader=None,
        value_diff_institute=None,
    )
    indexes = [_index(day) for day in opens]
    assert (
        abso_umr.abso_umr_value(
            opens,
            prices,
            flows,
            indexes,
            price_contract=PRICE_CONTRACT,
            money_flow_contract=FLOW_CONTRACT,
            index_contract=INDEX_CONTRACT,
        )
        is None
    )


@pytest.mark.unit
def test_abso_umr_rejects_duplicate_money_flow_keys() -> None:
    opens = _opens(69, date(2024, 6, 28))
    flows = [_flow(opens[0], "000001.SZ"), _flow(opens[0], "000001.SZ")]
    with pytest.raises(FeatureLookupError, match="资金流键重复"):
        abso_umr.abso_umr_value(
            opens,
            [],
            flows,
            [],
            price_contract=PRICE_CONTRACT,
            money_flow_contract=FLOW_CONTRACT,
            index_contract=INDEX_CONTRACT,
        )


# ----------------------------------------------------------------- panel


@pytest.mark.unit
def test_panel_emits_all_three_factors_for_one_event_and_skips_missing() -> None:
    opens = _opens(69, date(2024, 6, 28))
    prices = [_price(day, "000001.SZ", pct="1") for day in opens]
    flows = [_flow(day, "000001.SZ", act="100") for day in opens]
    indexes = [_index(day) for day in opens]
    # 第二只股票没有任何资金流，三个因子都不应产行。
    prices += [_price(day, "600000.SH") for day in opens]
    rows = build_money_flow_factor_values(
        prices,
        flows,
        indexes,
        opens,
        price_contract=PRICE_CONTRACT,
        money_flow_contract=FLOW_CONTRACT,
        index_contract=INDEX_CONTRACT,
        start=opens[-1],
        end=opens[-1],
        computed_at=datetime(2026, 11, 25),
        run_id="unit",
    )
    by_feature = {row.feature_id: row for row in rows}
    assert set(by_feature) == {
        abso_umr.FEATURE_ID,
        moneyflowh.FEATURE_ID,
        actlargemedcut.FEATURE_ID,
    }
    assert {row.asset_id for row in rows} == {"000001.SZ"}
    for row in rows:
        assert row.event_dt == opens[-1]
        assert row.asset_class == "stock"
        assert row.pit_grade == "A"
    assert by_feature[moneyflowh.FEATURE_ID].value == pytest.approx(-0.5)


@pytest.mark.unit
def test_own_row_window_is_the_last_twenty_stock_rows_not_calendar_days() -> None:
    # 个股有停牌空档：窗口按个股自有行数，不按开市日补齐。
    rows = [_price(date(2024, 1, 2) + timedelta(days=i), "000001.SZ") for i in range(25)]
    rows = rows[:5] + rows[10:]
    window = last_n_trading_days(
        rows, event_dt=rows[-1].trade_dt, count=20, trade_dt=lambda item: item.trade_dt
    )
    assert window is not None
    assert len(window) == 20
    assert window[0] is rows[-20]
