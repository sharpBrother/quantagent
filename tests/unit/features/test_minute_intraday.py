"""日内统计：与旧仓 pandas 调用路径逐项对照，并固定裁定口径。"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
import pytest

from quantagent.features.library.minute.intraday import is_pandas_zero_variance, minute_day_stats


def _legacy_pandas(close: list[float], vol: list[float]) -> dict[str, float | None]:
    """照着 factor_min.py 的 get_min_data 与四个因子的 process 写出的参考实现。"""
    frame = pd.DataFrame({"close": close, "vol": vol})
    frame["pctchg"] = frame["close"].pct_change(fill_method=None)
    frame = frame.dropna(how="any")
    pctchg = frame["pctchg"]
    volume = frame["vol"]
    out: dict[str, float | None] = {}
    out["corr_vrlag"] = _nan_to_none(volume.corr(pctchg.shift(1)))
    out["real_kurt"] = _nan_to_none(pctchg.kurt())
    rv = pctchg.std(ddof=1)
    for name, sign in (("ratio_realupvar", 1), ("ratio_realdownvar", -1)):
        picked = pctchg[pctchg > 0] if sign > 0 else pctchg[pctchg < 0]
        if not rv > 0:
            out[name] = None
        elif len(picked) > 1:
            out[name] = _nan_to_none(picked.std(ddof=1) / rv)
        else:
            # 旧代码此处返回 0（假 0）。新实现记为缺失，另行断言。
            out[name] = 0.0
    return out


def _nan_to_none(value: Any) -> float | None:
    return None if value is None or math.isnan(float(value)) else float(value)


def _random_day(seed: int, n: int = 241) -> tuple[list[float], list[float]]:
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0, 0.002, size=n)
    close = np.round(10 * np.cumprod(1 + steps), 2)
    vol = rng.integers(0, 500, size=n).astype(float)
    vol[rng.random(n) < 0.06] = 0.0
    return close.tolist(), vol.tolist()


@pytest.mark.unit
@pytest.mark.parametrize("seed", [1, 2, 3, 7, 11])
def test_matches_legacy_pandas_on_random_days(seed: int) -> None:
    close, vol = _random_day(seed)
    expected = _legacy_pandas(close, vol)
    got = minute_day_stats(close, vol)
    assert got.corr_vrlag == pytest.approx(expected["corr_vrlag"], rel=1e-9, abs=1e-12)
    assert got.real_kurt == pytest.approx(expected["real_kurt"], rel=1e-9, abs=1e-12)
    # 比率在上涨（下跌）不超过 1 根时旧值为 0，新值为缺失。其余情况必须与旧值一致。
    for name in ("ratio_realupvar", "ratio_realdownvar"):
        value = getattr(got, name)
        if expected[name] == 0.0 and value is None:
            continue
        assert value == pytest.approx(expected[name], rel=1e-9, abs=1e-12)


@pytest.mark.unit
def test_ratio_is_missing_when_up_minutes_at_most_one() -> None:
    # 只有一根上涨收益，旧代码的 real_upvar 返回 0，比率随之为 0。这里必须是缺失。
    close = [10.0, 10.1, 10.1, 10.05, 10.0, 9.99, 9.99]
    vol = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    stats = minute_day_stats(close, vol)
    up_returns = [x for x in np.diff(close) / np.array(close[:-1]) if x > 0]
    assert len(up_returns) == 1
    assert stats.ratio_realupvar is None
    assert stats.ratio_realdownvar is not None


@pytest.mark.unit
def test_ratio_is_missing_when_down_minutes_at_most_one() -> None:
    close = [10.0, 10.1, 10.2, 10.3, 10.25, 10.3, 10.4]
    vol = [1.0] * 7
    stats = minute_day_stats(close, vol)
    down_returns = [x for x in np.diff(close) / np.array(close[:-1]) if x < 0]
    assert len(down_returns) == 1
    assert stats.ratio_realdownvar is None
    assert stats.ratio_realupvar is not None


@pytest.mark.unit
def test_flat_day_gives_missing_kurt_ratio_and_corr() -> None:
    # 整日不动：收益率全为 0，方差为 0。pandas kurt 会返回 0（旧表假 0），这里记为缺失；
    # 比率与 corr 同样缺失。
    close = [10.0] * 240
    vol = [0.0] * 240
    stats = minute_day_stats(close, vol)
    assert stats.real_kurt is None
    assert stats.corr_vrlag is None
    assert stats.ratio_realupvar is None
    assert stats.ratio_realdownvar is None


@pytest.mark.unit
def test_constant_nonzero_returns_give_missing_kurt() -> None:
    # 每根收益都是 1%，方差为 0（浮点误差只在 1e-17 量级），峰度记为缺失，不是 0。
    close = [10.0 * 1.01**k for k in range(240)]
    vol = [1.0] * 240
    assert minute_day_stats(close, vol).real_kurt is None


@pytest.mark.unit
def test_kurt_needs_at_least_four_returns() -> None:
    # 4 根 bar 只有 3 个收益率，旧 pandas kurt 返回 NaN。
    stats = minute_day_stats([10.0, 10.1, 10.2, 10.3], [1.0, 2.0, 3.0, 4.0])
    assert stats.real_kurt is None


@pytest.mark.unit
def test_corr_pairs_volume_with_previous_return() -> None:
    # 旧代码 volume.corr(pctchg.shift(1))：第 j 根成交量与第 j-1 根收益率配对，首尾各少一对。
    close = [10.0, 10.2, 10.1, 10.4, 10.3, 10.6, 10.5]
    vol = [5.0, 1.0, 8.0, 2.0, 9.0, 3.0, 7.0]
    rets = [close[i + 1] / close[i] - 1 for i in range(len(close) - 1)]
    x = vol[2:]
    y = rets[:-1]
    expected = float(np.corrcoef(x, y)[0, 1])
    assert minute_day_stats(close, vol).corr_vrlag == pytest.approx(expected, rel=1e-12)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("close", "vol"),
    [
        ([10.0, 0.0, 10.0], [1.0, 1.0, 1.0]),
        ([10.0, -1.0, 10.0], [1.0, 1.0, 1.0]),
        ([10.0, float("nan"), 10.0], [1.0, 1.0, 1.0]),
        ([10.0, 10.0, 10.0], [1.0, -1.0, 1.0]),
        ([10.0, 10.0, 10.0], [1.0, float("inf"), 1.0]),
    ],
)
def test_rejects_non_positive_or_non_finite_inputs(close: list[float], vol: list[float]) -> None:
    with pytest.raises(ValueError):
        minute_day_stats(close, vol)


@pytest.mark.unit
def test_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError):
        minute_day_stats([10.0, 10.1], [1.0])


def _closes_from_returns(rets: list[float], start: float = 10.0) -> list[float]:
    closes = [start]
    for r in rets:
        closes.append(closes[-1] * (1.0 + r))
    return closes


@pytest.mark.unit
def test_exactly_equal_returns_are_pandas_zero_variance_and_missing() -> None:
    # 每根收益完全相同：pandas 的分母为 0，kurt 返回 0。这里记为缺失。
    rets = [0.01] * 240
    assert is_pandas_zero_variance(rets)
    assert pd.Series(rets).kurt() == 0.0
    assert minute_day_stats(_closes_from_returns(rets), [1.0] * 241).real_kurt is None


@pytest.mark.unit
def test_plus_minus_micro_returns_are_pandas_zero_variance_and_missing() -> None:
    # ±1e-6 的交替收益，240 根：m2 约 2.4e-10，分母 (n-2)(n-3)·m2² 约 3e-15，低于 pandas 的 1e-14 阈值。
    # 这类序列在旧表中存为假 0，新实现记为缺失。
    rets = [1e-6 if k % 2 == 0 else -1e-6 for k in range(240)]
    assert is_pandas_zero_variance(rets)
    assert pd.Series(rets).kurt() == 0.0
    assert minute_day_stats(_closes_from_returns(rets), [1.0] * 241).real_kurt is None


@pytest.mark.unit
def test_normal_returns_are_not_zero_variance_and_match_pandas() -> None:
    rng = np.random.default_rng(5)
    rets = rng.normal(0.0, 0.002, size=240).tolist()
    assert not is_pandas_zero_variance(rets)
    # pandas-stubs 对 Series.kurt 的返回类型过宽，这里显式标为 Any。
    pandas_kurt: Any = pd.Series(rets, dtype="float64").kurt()
    got = minute_day_stats(_closes_from_returns(rets), [1.0] * 241).real_kurt
    assert got == pytest.approx(float(pandas_kurt), rel=1e-9)


@pytest.mark.unit
@pytest.mark.parametrize("scale", [1e-6, 1e-5, 1e-4, 1e-3])
def test_pandas_zero_variance_judgement_agrees_with_pandas(scale: float) -> None:
    # 判定式与 pandas 的 Series.kurt() == 0 逐一对照，覆盖分母在阈值两侧的尺度。
    rng = np.random.default_rng(int(scale * 1e9) % 2**32)
    for n in (4, 5, 10, 60, 240):
        rets = (rng.choice([-1.0, 1.0], size=n) * scale).tolist()
        assert is_pandas_zero_variance(rets) == (pd.Series(rets).kurt() == 0.0), (n, scale)


@pytest.mark.unit
def test_fewer_than_four_returns_is_not_pandas_zero_variance() -> None:
    # pandas 对不足 4 个收益返回 NaN，不是 0，因此不属于零方差判定。
    assert not is_pandas_zero_variance([0.01, 0.01, 0.01])
