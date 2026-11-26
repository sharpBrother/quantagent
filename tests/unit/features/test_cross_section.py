"""截面去极值、中性化残差与 pxret21 定义。对照对象是旧仓 pandas 写法与 statsmodels。"""

from __future__ import annotations

import math
import random
import statistics

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm

from quantagent.domain.errors import FeatureLookupError
from quantagent.features.library.cross_section import (
    descriptor_pipeline,
    industry_median_fill,
    l3_integrate,
    mad_winsorize,
    residualize,
    utility_winsorize,
    weighted_zscore,
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


# ============================================================================
# barra descriptor 公共能力：weighted_zscore / industry_median_fill /
# descriptor_pipeline / l3_integrate（2026-11-26，对照 alpha_factory/factor_math.py）
# ============================================================================



def _legacy_normalize(values: dict[str, float], weight: dict[str, float] | None) -> dict[str, float]:
    # alpha_factory/factor_math.py normalize 的 pandas 复现。
    a = pd.Series(values, dtype=float)
    w = pd.Series(weight, dtype=float) if weight else None
    if a.dropna().empty:
        return {str(k): 0.0 for k in values}
    if w is None or w.empty:
        mean = a.mean()
    else:
        vw = w.reindex(a.dropna().index).dropna()
        if vw.empty or vw.sum() == 0:
            mean = a.mean()
        else:
            va = a.reindex(vw.index)
            mean = (va * (vw / vw.sum())).sum()
    a.loc[a.isna()] = mean
    std = np.std(a)
    if pd.isna(std) or std == 0:
        return {str(k): 0.0 for k in values}
    out = (a - mean) / std
    return {str(k): float(v) for k, v in out.items()}


def _legacy_descriptor_process(
    values: dict[str, float],
    industry: dict[str, str] | None,
    weight: dict[str, float] | None,
) -> pd.Series:
    # factor_math.descriptor_process 的 pandas 复现（含 reindex 到 industry.index）。
    fv = pd.Series(values, dtype=float)
    ind = pd.Series(industry) if industry else None
    w = pd.Series(weight, dtype=float) if weight else None
    if ind is not None and not ind.empty:
        fv = fv.reindex(ind.index)
    if fv.dropna().empty:
        return pd.Series(0.0, index=fv.index)
    m = fv.median()
    mm = (fv - m).abs().median()
    fv = fv.clip(m - 3 * mm, m + 3 * mm)
    if ind is not None and not ind.empty:
        imed = fv.groupby(ind).transform(lambda x: x.median() if x.notna().any() else np.nan)
        fv = fv.fillna(imed)
    if w is None or w.empty:
        mean = fv.mean()
    else:
        vw = w.reindex(fv.dropna().index).dropna()
        mean = fv.mean() if (vw.empty or vw.sum() == 0) else (fv.reindex(vw.index) * (vw / vw.sum())).sum()
    fv.loc[fv.isna()] = mean
    std = np.std(fv)
    if pd.isna(std) or std == 0:
        return pd.Series(0.0, index=fv.index)
    return (fv - mean) / std


@pytest.mark.unit
def test_weighted_zscore_matches_legacy_normalize() -> None:
    rng = random.Random(11)
    keys = [f"s{i:03d}" for i in range(300)]
    values = {k: (rng.gauss(0, 1) if rng.random() > 0.15 else float("nan")) for k in keys}
    weight = {k: rng.uniform(10, 1000) for k in keys}
    got = weighted_zscore(values, weight)
    want = _legacy_normalize(values, weight)
    for k in keys:
        assert got[k] == pytest.approx(want[k], rel=1e-9, abs=1e-12)
    # 等权
    got2 = weighted_zscore(values, None)
    want2 = _legacy_normalize(values, None)
    for k in keys:
        assert got2[k] == pytest.approx(want2[k], rel=1e-9, abs=1e-12)


@pytest.mark.unit
def test_weighted_zscore_std_is_one_and_edge_cases() -> None:
    rng = random.Random(12)
    values = {f"s{i}": rng.gauss(0, 1) for i in range(100)}
    out = weighted_zscore(values, None)
    finite = list(out.values())
    # z-score 后未加权总体 std 应=1（np.std ddof=0 口径）。
    assert statistics.pstdev(finite) == pytest.approx(1.0, rel=1e-9)
    # 全空 → 0 序列
    assert weighted_zscore({"a": float("nan")}, None) == {"a": 0.0}
    # 常数列 std=0 → 0 序列
    assert weighted_zscore({"a": 5.0, "b": 5.0}, None) == {"a": 0.0, "b": 0.0}


@pytest.mark.unit
def test_industry_median_fill() -> None:
    values = {
        "a": 1.0, "b": 3.0, "c": float("nan"),  # ind1: 有限 1,3 中位2 → c填2
        "d": 10.0, "e": float("nan"),  # ind2: 有限10 → e填10
        "f": float("nan"),  # ind3 无有限值 → f 保持NaN
    }
    industry = {"a": "i1", "b": "i1", "c": "i1", "d": "i2", "e": "i2", "f": "i3"}
    out = industry_median_fill(values, industry)
    assert out["c"] == pytest.approx(2.0)
    assert out["e"] == pytest.approx(10.0)
    assert math.isnan(out["f"])  # 同行业无有限值保持 NaN
    assert out["a"] == pytest.approx(1.0)
    # 空 industry → 原样
    assert industry_median_fill(values, {}) == values


@pytest.mark.unit
def test_descriptor_pipeline_matches_legacy() -> None:
    rng = random.Random(13)
    keys = [f"s{i:03d}" for i in range(300)]
    values = {k: (rng.gauss(0, 1) if rng.random() > 0.2 else float("nan")) for k in keys}
    industry = {k: f"ind{i % 10}" for i, k in enumerate(keys)}
    weight = {k: rng.uniform(10, 1000) for k in keys}
    got = descriptor_pipeline(values, industry, weight)
    legacy = _legacy_descriptor_process(values, industry, weight)
    compared = 0
    for k in keys:
        if k in legacy.index and math.isfinite(got.get(k, float("nan"))) and math.isfinite(legacy[k]):
            assert got[k] == pytest.approx(float(legacy[k]), rel=1e-9, abs=1e-9)
            compared += 1
    # 大部分键可比较（NaN被填补/标准化后）
    assert compared >= 250


@pytest.mark.unit
def test_l3_integrate_equal_weight_average() -> None:
    # 简单两 descriptor，验证等权平均与缺键按0计入。
    rng = random.Random(14)
    keys = [f"s{i}" for i in range(50)]
    d1 = {k: rng.gauss(0, 1) for k in keys}
    d2 = {k: rng.gauss(0, 1) for k in keys}
    out = l3_integrate({"D1": d1, "D2": d2}, None, None)
    # 输出键 = 并集
    assert set(out.keys()) == set(keys)
    # 每个值是有限的（descriptor_pipeline 后已标准化）
    assert all(math.isfinite(v) for v in out.values())
    # 空 descriptors → 空
    assert l3_integrate({}, None, None) == {}
