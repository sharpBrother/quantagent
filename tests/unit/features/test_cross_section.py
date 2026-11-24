"""截面去极值、中性化残差与 pxret21 定义。对照对象是旧仓 pandas 写法与 statsmodels。"""

from __future__ import annotations

import math
import random

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm

from quantagent.domain.errors import FeatureLookupError
from quantagent.features.library.cross_section import (
    mad_winsorize,
    residualize,
    utility_winsorize,
)
from quantagent.features.panel.minute_2b import pxret21


def _dict_to_series(values: dict[str, float]) -> pd.Series:
    return pd.Series(values, dtype=float).sort_index()


def _pandas_mad(values: dict[str, float]) -> dict[str, float]:
    # alpha_factory/preprocessing.py 第 47-66 行 winsorize_series 的 mad 分支，k=3。
    item = _dict_to_series(values)
    median = item.median()
    mad = (item - median).abs().median()
    if pd.isna(mad) or mad == 0:
        return dict(values)
    clipped = item.clip(lower=median - 3.0 * mad, upper=median + 3.0 * mad)
    return {str(k): float(v) for k, v in clipped.items()}


def _pandas_utility(values: dict[str, float]) -> dict[str, float]:
    # alpha_factory/factor_math.py 第 50-74 行 winsorize 的一般分支，k=3。
    item = _dict_to_series(values)
    m = item.median()
    mm = (item - m).abs().median()
    clipped = item.clip(m - 3 * mm, m + 3 * mm)
    return {str(k): float(v) for k, v in clipped.items()}


@pytest.mark.unit
def test_mad_winsorize_matches_pandas_and_keeps_zero_mad_unclipped() -> None:
    rng = random.Random(7)
    values = {f"s{i:03d}": rng.gauss(0, 1) * (10 if i % 9 == 0 else 1) for i in range(200)}
    got = mad_winsorize(values)
    want = _pandas_mad(values)
    for key in values:
        assert got[key] == pytest.approx(want[key], rel=1e-12)
    # MAD 为 0 时不裁剪：一半相同、一半不同，中位数上的 MAD 为 0。
    flat = {"a": 1.0, "b": 1.0, "c": 1.0, "d": 50.0}
    assert mad_winsorize(flat) == flat


@pytest.mark.unit
def test_utility_winsorize_clips_to_median_when_mad_is_zero() -> None:
    # 与 MAD 去极值不同：工具去极值在 MAD 为 0 时裁成中位数（factor_math.winsorize 没有零 MAD 分支）。
    flat = {"a": 1.0, "b": 1.0, "c": 1.0, "d": 50.0}
    got = utility_winsorize(flat)
    assert got == {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0}


@pytest.mark.unit
def test_utility_winsorize_matches_pandas_with_nan_free_input() -> None:
    rng = random.Random(9)
    values = {f"s{i:03d}": rng.gauss(0, 0.05) for i in range(300)}
    got = utility_winsorize(values)
    want = _pandas_utility(values)
    for key in values:
        assert got[key] == pytest.approx(want[key], rel=1e-12)


@pytest.mark.unit
def test_residualize_matches_statsmodels_with_intercept_and_skips_missing() -> None:
    rng = random.Random(3)
    keys = [f"s{i:03d}" for i in range(120)]
    x = {k: rng.gauss(0, 0.1) for k in keys}
    y = {k: 2.0 + 3.0 * x[k] + rng.gauss(0, 0.01) for k in keys}
    # 缺一边的样本不进回归，残差不写出；y 的 NaN 同样剔除。
    del x["s005"]
    y["s006"] = float("nan")
    got = residualize(y, x, min_obs=20)
    assert "s005" not in got
    assert "s006" not in got
    usable = sorted(k for k in keys if k in x and math.isfinite(y[k]))
    design = sm.add_constant(np.array([x[k] for k in usable]), has_constant="add")
    fitted = sm.OLS(np.array([y[k] for k in usable]), design).fit().predict(design)
    want = np.array([y[k] for k in usable]) - fitted
    for k, value in zip(usable, want, strict=True):
        assert got[k] == pytest.approx(float(value), rel=1e-10, abs=1e-12)


@pytest.mark.unit
def test_residualize_fails_closed_below_min_obs() -> None:
    # 旧代码样本不足时返回未中性化的 y；这里抛错，不回退。
    y = {f"s{i}": float(i) for i in range(10)}
    x = {f"s{i}": float(i * 2) for i in range(10)}
    with pytest.raises(FeatureLookupError, match="少于 20"):
        residualize(y, x, min_obs=20)


@pytest.mark.unit
def test_pxret21_uses_start_price_as_base_and_is_missing_on_gaps() -> None:
    assert pxret21(10.0, 12.0) == pytest.approx(0.2)
    # 分母取绝对值：负价不会出现在复权价上，但口径与旧 SQL 的 ABS 一致。
    assert pxret21(-10.0, -12.0) == pytest.approx(-0.2)
    assert pxret21(None, 12.0) is None
    assert pxret21(10.0, None) is None
    assert pxret21(0.0, 12.0) is None
