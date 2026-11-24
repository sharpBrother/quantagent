"""MIF 单元测试：pandas 旧写法对拍、窗口、缺失、方差 0、停牌、滞后方向、非交易日行、符号与血缘。不读存储。"""

from __future__ import annotations

import math
import random
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pandas as pd
import pytest

from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.derivative_indicator.types import Turnover
from quantagent.domain.prices.types import DailyPrice
from quantagent.features.library.price import mif
from quantagent.features.library.price.mif import mif_value, night_ratio
from quantagent.features.panel.mif import build_mif_values

if TYPE_CHECKING:
    from quantagent.domain.feature_value import FeatureValue

CODE = "000001.SZ"
RUN_AT = datetime(2026, 11, 25, 0, 0, 0)


def _contract(dataset: str, grade: str = "A") -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": dataset,
            "doc_ref": "docs/contracts/src-wind-first-batch.md",
            "temporal_kind": "point_event",
            "event_field": "TRADE_DT",
            "visibility": {
                "rule": "same_day_close",
                "grade": grade,
                "rationale": "单元测试用的可见性规则说明，长度足够通过契约校验",
            },
            "pit_recoverable": True,
        }
    )


PRICE_CONTRACT = _contract("src.wind.ashareeodprices")
TURN_CONTRACT = _contract("src.wind.ashareeodderivativeindicator")


def _weekdays(count: int, first: date = date(2024, 1, 2)) -> list[date]:
    days: list[date] = []
    cursor = first
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _price(
    day: date,
    *,
    adj_open: str | None = "10.1",
    adj_preclose: str | None = "10",
    status: int | None = -1,
    code: str = CODE,
) -> DailyPrice:
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
        adj_open=None if adj_open is None else Decimal(adj_open),
        adj_preclose=None if adj_preclose is None else Decimal(adj_preclose),
        trade_status_code=status,
    )


def _turn(day: date, value: str | None, code: str = CODE) -> Turnover:
    return Turnover(
        trade_dt=day,
        wind_code=code,
        turnover=None if value is None else Decimal(value),
    )


def _random_prices(days: list[date], seed: int) -> list[DailyPrice]:
    rng = random.Random(seed)
    rows: list[DailyPrice] = []
    for day in days:
        preclose = Decimal(f"{rng.uniform(5, 50):.4f}")
        opened = (preclose * Decimal(f"{rng.uniform(0.9, 1.1):.6f}")).quantize(Decimal("0.0001"))
        rows.append(_price(day, adj_open=str(opened), adj_preclose=str(preclose)))
    return rows


def _random_turnover(days: list[date], seed: int) -> list[Turnover]:
    rng = random.Random(seed)
    return [_turn(day, f"{rng.uniform(0.5, 8):.4f}") for day in days]


def _legacy_mif(
    prices: list[DailyPrice],
    turnovers: list[Turnover],
    ob_date: date,
) -> float | None:
    """旧仓 ``factors/daily_factor.py`` 的 get_stock_data（col_lag night 0、turnover 1，tail 20）加 ``MIF.cal``。
    换手先按价格行左连接，与旧仓 ``eod_price.join(deri_indicator)`` 一致。
    ``loc[:ob_date]`` 在旧仓是按交易日截止，这里按位置截到 ``ob_date`` 所在价格行，结果相同。
    """
    by_day = {t.trade_dt: t.turnover for t in turnovers}
    stop = next(i for i, row in enumerate(prices) if row.trade_dt == ob_date) + 1
    night_values = [_as_float(night_ratio(row)) for row in prices[:stop]]
    turn_values = [_as_float(by_day.get(row.trade_dt)) for row in prices[:stop]]
    night = pd.Series(night_values, dtype=float)
    turn = pd.Series(turn_values, dtype=float)
    df = pd.DataFrame()
    df["night_ratio"] = night.shift(0).tail(20)
    df["S_DQ_TURN"] = turn.shift(1).tail(20)
    if len(df) < 20:
        return None
    if not df.notna().all().all():
        return None
    value = df["night_ratio"].abs().corr(df["S_DQ_TURN"])
    return None if pd.isna(value) else float(value)


def _as_float(value: Decimal | None) -> float:
    """缺失映射为 NaN，与旧仓 DataFrame 里的空值一致。"""
    return math.nan if value is None else float(value)


def _window(prices: list[DailyPrice], end_index: int) -> list[DailyPrice]:
    span = mif.WINDOW + mif.LAG
    return prices[end_index - span + 1 : end_index + 1]


def _panel(
    prices: list[DailyPrice], turnovers: list[Turnover], days: list[date]
) -> tuple[FeatureValue, ...]:
    return build_mif_values(
        prices,
        turnovers,
        price_contract=PRICE_CONTRACT,
        turnover_contract=TURN_CONTRACT,
        start=days[0],
        end=days[-1],
        computed_at=RUN_AT,
        run_id="run",
    )


def _run(window: list[DailyPrice], turnovers: list[Turnover]) -> mif.MifValue | None:
    return mif_value(
        window,
        {t.trade_dt: t for t in turnovers},
        price_contract=PRICE_CONTRACT,
        turnover_contract=TURN_CONTRACT,
    )


# ---------- night_ratio 口径 ----------


def test_night_ratio_uses_adj_open_over_adj_preclose() -> None:
    value = night_ratio(_price(date(2024, 1, 2), adj_open="10.5", adj_preclose="10"))
    assert value == Decimal("5")


def test_night_ratio_rounds_to_four_decimals_half_up() -> None:
    # 旧表 stock_ratio.night_ratio 是 numeric(20,4)，旧 MIF 的输入精度就是 4 位。
    # 100 * (10.000005 / 10 - 1) 恰为 0.00005，HALF_UP 进位到 0.0001；HALF_EVEN 会得到 0.0000。
    assert night_ratio(
        _price(date(2024, 1, 2), adj_open="10.000005", adj_preclose="10")
    ) == Decimal("0.0001")
    assert night_ratio(_price(date(2024, 1, 2), adj_open="9.999995", adj_preclose="10")) == Decimal(
        "-0.0001"
    )
    value = night_ratio(_price(date(2024, 1, 2), adj_open="10.12345", adj_preclose="10"))
    assert value == Decimal("1.2345")


def test_night_ratio_halted_row_is_missing_not_zero() -> None:
    # 停牌行的开盘价是 Wind 填的前收盘价，不是观测，必须记缺失而不是 0。
    assert night_ratio(_price(date(2024, 1, 2), status=0)) is None


def test_night_ratio_rejects_missing_or_non_positive_preclose() -> None:
    assert night_ratio(_price(date(2024, 1, 2), adj_open=None)) is None
    assert night_ratio(_price(date(2024, 1, 2), adj_preclose=None)) is None
    assert night_ratio(_price(date(2024, 1, 2), adj_preclose="0")) is None
    assert night_ratio(_price(date(2024, 1, 2), adj_preclose="-1")) is None


# ---------- 数值与旧仓对拍 ----------


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_matches_legacy_pandas_on_every_full_window(seed: int) -> None:
    days = _weekdays(60)
    prices = _random_prices(days, seed)
    turnovers = _random_turnover(days, seed + 100)
    for end_index in range(mif.WINDOW + mif.LAG - 1, len(days)):
        window = _window(prices, end_index)
        ob = days[end_index]
        expected = _legacy_mif(prices[: end_index + 1], turnovers[: end_index + 1], ob)
        got = _run(window, turnovers[end_index - (mif.WINDOW + mif.LAG) + 1 : end_index + 1])
        assert expected is not None
        assert got is not None
        # 旧仓 corr 是 float64，本仓是 60 位 Decimal，差在浮点舍入之内。
        assert float(-got.raw) == pytest.approx(-expected, abs=1e-9)


def test_value_is_negated_raw_correlation() -> None:
    days = _weekdays(21)
    prices = _random_prices(days, 7)
    turnovers = _random_turnover(days, 8)
    got = _run(prices, turnovers)
    assert got is not None
    assert got.value == -got.raw
    assert math.isfinite(float(got.raw))
    assert -1 <= float(got.raw) <= 1


# ---------- 窗口 ----------


def test_window_needs_twenty_one_rows() -> None:
    days = _weekdays(21)
    prices = _random_prices(days, 11)
    turnovers = _random_turnover(days, 12)
    assert _run(prices[:20], turnovers[:20]) is None
    assert _run(prices, turnovers) is not None


def test_panel_skips_rows_before_full_window() -> None:
    days = _weekdays(25)
    prices = _random_prices(days, 21)
    turnovers = _random_turnover(days, 22)
    rows = build_mif_values(
        prices,
        turnovers,
        price_contract=PRICE_CONTRACT,
        turnover_contract=TURN_CONTRACT,
        start=days[0],
        end=days[-1],
        computed_at=RUN_AT,
        run_id="run",
    )
    assert [row.event_dt for row in rows] == days[20:]
    assert {row.feature_id for row in rows} == {mif.FEATURE_ID}
    assert {row.param_hash for row in rows} == {mif.PARAM_HASH}


def test_panel_window_is_per_stock_own_rows() -> None:
    # 另一只股票的行不进入本股票的 21 行窗口。
    days = _weekdays(21)
    prices = _random_prices(days, 31)
    other = [replace(row, wind_code="600000.SH") for row in _random_prices(days, 33)]
    turnovers = _random_turnover(days, 32) + [
        replace(item, wind_code="600000.SH") for item in _random_turnover(days, 34)
    ]
    solo = build_mif_values(
        prices,
        turnovers[: len(days)],
        price_contract=PRICE_CONTRACT,
        turnover_contract=TURN_CONTRACT,
        start=days[0],
        end=days[-1],
        computed_at=RUN_AT,
        run_id="run",
    )
    mixed = build_mif_values(
        prices + other,
        turnovers,
        price_contract=PRICE_CONTRACT,
        turnover_contract=TURN_CONTRACT,
        start=days[0],
        end=days[-1],
        computed_at=RUN_AT,
        run_id="run",
    )
    assert [row for row in mixed if row.asset_id == CODE] == list(solo)


# ---------- 缺失 ----------


def test_null_turnover_value_in_window_gives_no_value() -> None:
    days = _weekdays(21)
    prices = _random_prices(days, 41)
    turnovers = _random_turnover(days, 42)
    turnovers[10] = _turn(days[10], None)
    assert _run(prices, turnovers) is None


def test_missing_turnover_row_gives_no_value() -> None:
    days = _weekdays(21)
    prices = _random_prices(days, 43)
    turnovers = _random_turnover(days, 44)
    del turnovers[5]
    assert _run(prices, turnovers) is None


def test_missing_adj_open_in_night_window_gives_no_value() -> None:
    days = _weekdays(21)
    prices = _random_prices(days, 45)
    prices[3] = _price(days[3], adj_open=None)
    assert _run(prices, _random_turnover(days, 46)) is None


# ---------- 方差 0 与接近常数 ----------


def test_constant_night_ratio_gives_no_value() -> None:
    # adj_open 等于 adj_preclose 时隔夜收益精确为 0，20 天全为 0 则相关无定义。
    days = _weekdays(21)
    prices = [_price(day, adj_open="10", adj_preclose="10") for day in days]
    assert _run(prices, _random_turnover(days, 51)) is None


def test_constant_turnover_gives_no_value() -> None:
    days = _weekdays(21)
    prices = _random_prices(days, 52)
    turnovers = [_turn(day, "1.2345") for day in days]
    assert _run(prices, turnovers) is None


def test_nearly_constant_turnover_is_not_mistaken_for_constant() -> None:
    days = _weekdays(21)
    prices = _random_prices(days, 53)
    turnovers = [_turn(day, "1.0000") for day in days]
    # days[-2] 的换手是窗口内最后一个滞后项；截面日当天的换手不进入相关。
    turnovers[-2] = _turn(days[-2], "1.0001")
    got = _run(prices, turnovers)
    assert got is not None
    expected = _legacy_mif(prices, turnovers, days[-1])
    assert expected is not None
    assert float(-got.raw) == pytest.approx(-expected, abs=1e-9)


# ---------- 停牌 ----------


def test_halted_row_inside_night_window_gives_no_value() -> None:
    days = _weekdays(21)
    prices = _random_prices(days, 61)
    prices[7] = _price(days[7], status=0, adj_open="10", adj_preclose="10")
    assert _run(prices, _random_turnover(days, 62)) is None


def test_halted_row_only_as_lag_source_keeps_value() -> None:
    # 第 0 行停牌只影响它自己的 night_ratio，而第 0 行只作为第 1 行换手的滞后源，不进入相关。
    days = _weekdays(21)
    prices = _random_prices(days, 63)
    prices[0] = _price(days[0], status=0, adj_open="10", adj_preclose="10")
    turnovers = _random_turnover(days, 64)
    got = _run(prices, turnovers)
    assert got is not None
    expected = _legacy_mif(prices, turnovers, days[-1])
    assert expected is not None
    assert float(-got.raw) == pytest.approx(-expected, abs=1e-9)


# ---------- 滞后方向 ----------


def test_turnover_is_lagged_one_price_row() -> None:
    days = _weekdays(21)
    prices = _random_prices(days, 71)
    turnovers = _random_turnover(days, 72)
    base = _run(prices, turnovers)
    assert base is not None
    # 截面日自己的换手不进入窗口。
    changed_last = [*turnovers[:-1], _turn(days[-1], "999")]
    assert _run(prices, changed_last) == base
    # 前一个价格行的换手进入窗口，改它结果必须变。
    changed_prev = [*turnovers[:-2], _turn(days[-2], "999"), turnovers[-1]]
    moved = _run(prices, changed_prev)
    assert moved is not None
    assert moved.raw != base.raw


# ---------- 衍生指标非交易日行 ----------


WEEKEND_A = date(2024, 1, 6)  # 周六，不在 _weekdays(21) 返回的交易日里
WEEKEND_B = date(2024, 1, 7)  # 周日


def test_turnover_rows_off_price_rows_are_dropped() -> None:
    days = _weekdays(21)
    assert WEEKEND_A not in days and WEEKEND_B not in days
    prices = _random_prices(days, 81)
    turnovers = _random_turnover(days, 82)
    noisy = [*turnovers, _turn(WEEKEND_A, "1000"), _turn(WEEKEND_B, "1000")]
    rows_clean = _panel(prices, turnovers, days)
    rows_noisy = _panel(prices, noisy, days)
    assert rows_noisy == rows_clean
    assert len(rows_clean) == 1  # 21 行窗口只在第 21 个交易日产一行
    assert {row.event_dt for row in rows_noisy} <= set(days)


def test_non_trading_turnover_does_not_shift_lag() -> None:
    # 非交易日行若被当作一行，会把滞后推到错误的价格行上。这里插入一条非交易日换手。
    days = _weekdays(21)
    prices = _random_prices(days, 83)
    turnovers = _random_turnover(days, 84)
    base = _run(prices, turnovers)
    assert base is not None
    inserted = [*turnovers, _turn(WEEKEND_A, "1000")]
    assert _run(prices, inserted) == base


# ---------- 血缘 ----------


def test_lineage_takes_worst_grade_and_latest_visible_day() -> None:
    days = _weekdays(21)
    prices = _random_prices(days, 91)
    turnovers = _random_turnover(days, 92)
    got = mif_value(
        prices,
        {t.trade_dt: t for t in turnovers},
        price_contract=PRICE_CONTRACT,
        turnover_contract=_contract("src.wind.ashareeodderivativeindicator", grade="B"),
    )
    assert got is not None
    assert got.pit_grade == "B"
    assert got.knowledge_dt == days[-1]
    assert got.event_dt == days[-1]
    assert got.asset_id == CODE
