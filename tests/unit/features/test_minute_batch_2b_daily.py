"""第二批分钟日值（corr_vrlaglarge、core_up、core_down）与旧仓 pandas 代码逐日对拍。

对拍对象是把 ``factors/factor_min.py`` 第 637-687 行的写法原样搬到 pandas 上：``get_min_data`` 的
``pct_change`` + ``dropna``，再 ``sort_values(ascending=False)``、``.corr``、``np.dot``。
输入刻意带大量并列（小整数成交量、零收益），让排序的并列顺序成为被检验的部分。
"""

from __future__ import annotations

import math
import random

import numpy as np
import pandas as pd
import pytest

from quantagent.features.library.minute.batch_2b import minute_day_2b

# 常量收益或常量成交量时 numpy 的 corrcoef 会除零，旧代码返回 NaN，两边的结果都是缺失。
pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")


def _legacy_day(
    closes: list[float], volumes: list[float]
) -> tuple[float | None, float | None, float | None]:
    """旧代码的 pandas 写法。``dc`` 为 dropna 后的当日分钟表，index 0..N-2。"""
    dc = pd.DataFrame({"close": closes, "vol": volumes})
    dc["pctchg"] = dc["close"].pct_change()
    dc = dc.dropna(how="any").reset_index(drop=True)
    volume = dc["vol"]
    pctchg = dc["pctchg"]
    tlen = len(volume)
    large_t = volume.sort_values(ascending=False).index[: round(tlen / 3)]
    corr = volume.loc[large_t].corr(pctchg.shift(1).loc[large_t])

    series = pctchg.copy()
    series.index = pd.RangeIndex(1, len(series) + 1)
    up_pct = series[series > 0]
    down_pct = series[series < 0]
    up = _ratio(np.dot(up_pct.index, up_pct), math.sqrt((up_pct**2).sum()))
    down = _ratio(np.dot(down_pct.index, down_pct), math.sqrt((down_pct**2).sum()))
    return _finite(corr), up, down


def _ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return float(numerator) / float(denominator)


def _finite(value: float) -> float | None:
    return None if value is None or math.isnan(value) else float(value)


def _random_day(rng: random.Random, n: int) -> tuple[list[float], list[float]]:
    price = 10.0
    closes: list[float] = []
    for _ in range(n):
        # 价格取两位小数，制造零收益与大量相同收益，检验 core 的 > 0 / < 0 边界。
        price = max(0.01, round(price * (1 + rng.choice([-0.01, -0.002, 0.0, 0.002, 0.01])), 2))
        closes.append(price)
    volumes = [float(rng.randint(0, 5)) for _ in range(n)]
    return closes, volumes


def _assert_same(got: float | None, want: float | None) -> None:
    if want is None:
        assert got is None
    else:
        assert got is not None
        assert got == pytest.approx(want, rel=1e-9, abs=1e-12)


@pytest.mark.unit
@pytest.mark.parametrize("n", [2, 3, 4, 5, 17, 40, 241])
def test_daily_values_match_pandas_legacy_on_tie_heavy_days(n: int) -> None:
    rng = random.Random(20261124 + n)
    for _ in range(30):
        closes, volumes = _random_day(rng, n)
        got = minute_day_2b(closes, volumes)
        want = _legacy_day(closes, volumes)
        for g, w in zip(got, want, strict=True):
            _assert_same(g, w)


@pytest.mark.unit
def test_corr_top_third_uses_legacy_tie_order_not_time_order() -> None:
    # 全部成交量相同，前三分之一的选取完全由排序的并列顺序决定。时间顺序的前 N 根与旧代码不同。
    n = 241
    closes = [10.0 + 0.01 * ((i * 7) % 11) for i in range(n)]
    volumes = [100.0] * n
    volumes[50] = 900.0
    volumes[17] = 900.0
    got = minute_day_2b(closes, volumes)
    want = _legacy_day(closes, volumes)
    _assert_same(got[0], want[0])


@pytest.mark.unit
def test_core_is_missing_when_no_bar_moves_in_that_direction() -> None:
    # 只有上涨没有下跌：core_down 的分母为 0，按旧代码的 NaN 处理为缺失，不写 0。
    closes = [10.0, 10.1, 10.2, 10.3]
    volumes = [1.0, 2.0, 3.0, 4.0]
    _, up, down = minute_day_2b(closes, volumes)
    assert up is not None
    assert down is None


@pytest.mark.unit
def test_single_bar_day_has_no_values() -> None:
    assert minute_day_2b([10.0], [5.0]) == (None, None, None)


@pytest.mark.unit
def test_non_positive_price_is_rejected_not_treated_as_missing() -> None:
    with pytest.raises(ValueError, match="收盘价非正"):
        minute_day_2b([10.0, 0.0, 10.1], [1.0, 1.0, 1.0])


@pytest.mark.unit
def test_negative_volume_is_rejected() -> None:
    with pytest.raises(ValueError, match="成交量为负"):
        minute_day_2b([10.0, 10.1, 10.2], [1.0, -1.0, 1.0])
