"""真实波幅 UMR：开市日对齐，全缺失不是 0，血缘不能手填。"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.errors import FeatureLookupError
from quantagent.domain.index_returns.types import IndexReturn
from quantagent.domain.prices.types import DailyPrice
from quantagent.features.library.price.tr_umr import (
    BENCHMARK,
    DEFINITION_VERSION,
    FEATURE_ID,
    LOOKBACK,
    PARAM_HASH,
    PARAMS,
    RET_WINDOW,
    RISK_WINDOW,
    tr_umr_value,
)
from quantagent.features.panel.tr_umr import build_tr_umr_values
from quantagent.platform.identity import digest_json

_COMPUTED_AT = datetime(2024, 6, 1, 15, 0)
_RUN_ID = "run-tr-umr"


def _contract(dataset: str, doc_ref: str, grade: str) -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": dataset,
            "doc_ref": doc_ref,
            "temporal_kind": "point_event",
            "event_field": "TRADE_DT",
            "visibility": {
                "rule": "same_day_close",
                "grade": grade,
                "rationale": "TR_UMR 测试用的可见性规则说明足够长",
            },
            "pit_recoverable": True,
        }
    )


def _price_contract(grade: str = "A") -> VisibilityContract:
    return _contract(
        "src.wind.ashareeodprices", "docs/contracts/src-wind-ashareeodprices.md", grade
    )


def _index_contract(grade: str = "A") -> VisibilityContract:
    return _contract(
        "src.wind.aindexeodprices", "docs/contracts/src-wind-aindexeodprices.md", grade
    )


def _days(count: int) -> tuple[date, ...]:
    start = date(2024, 1, 2)
    return tuple(start + timedelta(days=offset) for offset in range(count))


def _levels(index: int) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    preclose = Decimal(1000 + index) / Decimal(100)
    high = preclose * (Decimal("1.01") + Decimal(index % 5) / Decimal(1000))
    low = preclose * (Decimal("0.992") - Decimal(index % 3) / Decimal(2000))
    stock = Decimal((index % 7) - 3) * Decimal("0.35")
    return preclose, high, low, stock


def _price(day: date, index: int, code: str = "000001.SZ") -> DailyPrice:
    preclose, high, low, stock = _levels(index)
    # 不复权高低价故意等于前收。用错字段时 TR 会变成 0。
    return DailyPrice(
        trade_dt=day,
        wind_code=code,
        open=preclose,
        high=preclose,
        low=preclose,
        close=preclose,
        volume=Decimal("1"),
        amount=Decimal("1"),
        pct_change=stock,
        adj_high=high,
        adj_low=low,
        adj_preclose=preclose,
    )


def _index(day: date, index: int, code: str = BENCHMARK) -> IndexReturn:
    benchmark = Decimal((index % 4) - 1) * Decimal("0.15")
    return IndexReturn(trade_dt=day, wind_code=code, pct_change=benchmark)


def _blank_price(day: date, code: str = "000001.SZ") -> DailyPrice:
    return DailyPrice(
        trade_dt=day,
        wind_code=code,
        open=None,
        high=None,
        low=None,
        close=None,
        volume=None,
        amount=None,
        pct_change=None,
        adj_high=None,
        adj_low=None,
        adj_preclose=None,
    )


def _components(
    prices: tuple[DailyPrice, ...],
    index_returns: tuple[IndexReturn, ...],
    open_days: tuple[date, ...],
) -> tuple[list[float], list[float]]:
    price_by_day = {row.trade_dt: row for row in prices}
    index_by_day = {row.trade_dt: row for row in index_returns}
    tr: list[float] = []
    excess: list[float] = []
    for day in open_days:
        row = price_by_day.get(day)
        index_row = index_by_day.get(day)
        if (
            row is None
            or row.adj_high is None
            or row.adj_low is None
            or row.adj_preclose is None
            or row.adj_preclose == 0
        ):
            tr.append(math.nan)
        else:
            high = float(row.adj_high)
            low = float(row.adj_low)
            preclose = float(row.adj_preclose)
            tr.append(max(high - low, abs(high - preclose), abs(low - preclose)) / preclose)
        if (
            row is None
            or row.pct_change is None
            or index_row is None
            or index_row.pct_change is None
        ):
            excess.append(math.nan)
        else:
            excess.append(float(row.pct_change) - float(index_row.pct_change))
    return tr, excess


def _oracle(tr: list[float], excess: list[float]) -> float:
    """独立预言：pandas rolling，权重按旧函数逐位写出。"""
    risk = pd.Series(tr, dtype="float64")
    coef = risk.rolling(RISK_WINDOW, min_periods=RISK_WINDOW).mean() - risk
    window = RET_WINDOW
    half_life = 30
    exp_wt = np.asarray([0.5 ** (1 / half_life)] * window) ** np.arange(window)
    weights = exp_wt[::-1] / np.sum(exp_wt)
    products = pd.Series(
        coef.iloc[-window:].to_numpy() * np.asarray(excess[-window:], dtype=np.float64) * weights,
        dtype="float64",
    )
    return float(products.sum(skipna=True))


def _assert_relative(actual: float, expected: float) -> None:
    scale = max(abs(actual), abs(expected))
    assert scale > 0
    assert abs(actual - expected) <= 1e-12 * scale


@pytest.mark.unit
def test_matches_pandas_rolling_oracle() -> None:
    assert set(PARAMS) == {
        "risk_window",
        "ret_window",
        "half_life",
        "benchmark",
        "sign",
        "mean_window",
    }
    assert PARAMS["sign"] == "1"
    assert all(
        isinstance(PARAMS[key], int)
        for key in ("risk_window", "ret_window", "half_life", "mean_window")
    )
    assert digest_json(PARAMS) == PARAM_HASH
    days = _days(LOOKBACK)
    prices = tuple(_price(day, index) for index, day in enumerate(days))
    other = tuple(_price(day, index, "000002.SZ") for index, day in enumerate(days))
    index_returns = tuple(_index(day, index) for index, day in enumerate(days))
    tr, excess = _components(prices, index_returns, days)
    expected = _oracle(tr, excess)
    assert abs(expected) > 1e-8
    got = tr_umr_value(
        days,
        prices,
        index_returns,
        price_contract=_price_contract(),
        index_contract=_index_contract(),
    )
    assert got is not None
    _assert_relative(got.value, expected)
    rows = build_tr_umr_values(
        (*other, *prices),
        index_returns,
        days,
        price_contract=_price_contract(),
        index_contract=_index_contract(),
        start=days[0],
        end=days[-1] + timedelta(days=2),
        computed_at=_COMPUTED_AT,
        run_id=_RUN_ID,
    )
    assert [row.asset_id for row in rows] == ["000001.SZ", "000002.SZ"]
    assert [row.event_dt for row in rows] == [days[-1], days[-1]]
    assert rows[0].asset_class == "stock"
    assert rows[0].feature_id == FEATURE_ID
    assert rows[0].definition_version == DEFINITION_VERSION
    assert rows[0].param_hash == PARAM_HASH
    assert isinstance(rows[0].value, float)
    _assert_relative(rows[0].value, expected)
    assert rows[0].value == rows[1].value
    assert rows[0].knowledge_dt == days[-1]
    assert rows[0].pit_grade == "A"


@pytest.mark.unit
def test_short_open_day_window_produces_no_value() -> None:
    days = _days(LOOKBACK - 1)
    prices = tuple(_price(day, index) for index, day in enumerate(days))
    index_returns = tuple(_index(day, index) for index, day in enumerate(days))
    assert (
        tr_umr_value(
            days,
            prices,
            index_returns,
            price_contract=_price_contract(),
            index_contract=_index_contract(),
        )
        is None
    )
    assert (
        build_tr_umr_values(
            prices,
            index_returns,
            days,
            price_contract=_price_contract(),
            index_contract=_index_contract(),
            start=days[0],
            end=days[-1],
            computed_at=_COMPUTED_AT,
            run_id=_RUN_ID,
        )
        == ()
    )


@pytest.mark.unit
def test_missing_stock_day_stays_missing() -> None:
    days = _days(LOOKBACK)
    prices = tuple(_price(day, index) for index, day in enumerate(days) if index != 20)
    index_returns = tuple(_index(day, index) for index, day in enumerate(days))
    tr, excess = _components(prices, index_returns, days)
    assert math.isnan(tr[20]) and math.isnan(excess[20])
    expected = _oracle(tr, excess)
    filled = _oracle(
        pd.Series(tr, dtype="float64").ffill().to_list(),
        pd.Series(excess, dtype="float64").ffill().to_list(),
    )
    assert abs(filled - expected) > 1e-8
    got = tr_umr_value(
        days,
        prices,
        index_returns,
        price_contract=_price_contract(),
        index_contract=_index_contract(),
    )
    assert got is not None
    _assert_relative(got.value, expected)


@pytest.mark.unit
def test_all_missing_is_none_not_zero() -> None:
    days = _days(LOOKBACK)
    blank = [math.nan] * LOOKBACK
    assert _oracle(blank, blank) == 0.0
    index_returns = tuple(_index(day, index) for index, day in enumerate(days))
    assert (
        tr_umr_value(
            days,
            (),
            index_returns,
            price_contract=_price_contract(),
            index_contract=_index_contract(),
        )
        is None
    )
    assert (
        tr_umr_value(
            days,
            tuple(_blank_price(day) for day in days),
            tuple(IndexReturn(day, BENCHMARK, None) for day in days),
            price_contract=_price_contract(),
            index_contract=_index_contract(),
        )
        is None
    )


@pytest.mark.unit
def test_lineage_takes_worst_grade_and_event_date() -> None:
    days = _days(LOOKBACK)
    prices = tuple(_price(day, index) for index, day in enumerate(days))
    index_returns = tuple(_index(day, index) for index, day in enumerate(days))
    got = tr_umr_value(
        days,
        prices,
        index_returns,
        price_contract=_price_contract("A"),
        index_contract=_index_contract("B"),
    )
    assert got is not None
    assert prices[-1].trade_dt == days[-1]
    assert index_returns[-1].trade_dt == days[-1]
    assert got.knowledge_dt == days[-1]
    assert got.pit_grade == "B"
    rows = build_tr_umr_values(
        prices,
        index_returns,
        days,
        price_contract=_price_contract("A"),
        index_contract=_index_contract("B"),
        start=days[-1],
        end=days[-1],
        computed_at=_COMPUTED_AT,
        run_id=_RUN_ID,
    )
    assert len(rows) == 1
    assert rows[0].knowledge_dt == days[-1]
    assert rows[0].pit_grade == "B"


@pytest.mark.unit
def test_duplicate_dates_fail() -> None:
    days = _days(LOOKBACK)
    prices = [_price(day, index) for index, day in enumerate(days)]
    index_returns = [_index(day, index) for index, day in enumerate(days)]
    with pytest.raises(FeatureLookupError, match="行情键重复"):
        tr_umr_value(
            days,
            (*prices, _price(days[10], 10)),
            index_returns,
            price_contract=_price_contract(),
            index_contract=_index_contract(),
        )
    with pytest.raises(FeatureLookupError, match="指数收益键重复"):
        tr_umr_value(
            days,
            prices,
            (*index_returns, _index(days[3], 3)),
            price_contract=_price_contract(),
            index_contract=_index_contract(),
        )
    duplicated_days = list(days)
    duplicated_days[5] = duplicated_days[4]
    with pytest.raises(FeatureLookupError, match="开市日重复"):
        tr_umr_value(
            duplicated_days,
            prices,
            index_returns,
            price_contract=_price_contract(),
            index_contract=_index_contract(),
        )


@pytest.mark.unit
def test_unexpected_index_code_fails() -> None:
    days = _days(LOOKBACK)
    prices = tuple(_price(day, index) for index, day in enumerate(days))
    index_returns = [_index(day, index) for index, day in enumerate(days)]
    index_returns[0] = IndexReturn(days[0], "000300.SH", Decimal("0.1"))
    with pytest.raises(FeatureLookupError, match=r"000985\.CSI"):
        tr_umr_value(
            days,
            prices,
            index_returns,
            price_contract=_price_contract(),
            index_contract=_index_contract(),
        )
