"""截面去极值与中性化的纯函数，数值口径与旧仓 ``alpha_factory`` 一致。

出处（pycharm_workspace）：

- MAD 去极值：``alpha_factory/preprocessing.py`` 第 47-66 行 ``winsorize_series(method="mad")``，k=3。
  中位数 ± k·MAD 裁剪；MAD 为 0 或缺失时原样返回，不裁剪。
- 工具去极值：``alpha_factory/factor_math.py`` 第 50-74 行 ``winsorize``，中位数 ± 3·MAD 裁剪。MAD 为 0 时
  裁成中位数，这一点与上面的 MAD 去极值不同。中性化的 x 用这一种。
- 中性化：``alpha_factory/preprocessing.py`` 第 114-143 行 ``neutralize``。statsmodels OLS 加截距，
  样本为 y 与全部 x 都有限的交集，残差 = y − fitted。

与旧代码的差异：有效样本数少于 ``min_obs`` 时，旧代码返回未中性化的 y。这里改为抛错，见
``docs/adr/2026-11-24-minute-factors-batch-2b.md``。
"""

from __future__ import annotations

import math
import statistics
from typing import TYPE_CHECKING

import numpy as np
import statsmodels.api as sm

from quantagent.domain.errors import FeatureLookupError

if TYPE_CHECKING:
    from collections.abc import Mapping

MAD_K = 3.0
MIN_NEUTRAL_OBS = 20


def mad_winsorize(values: Mapping[str, float]) -> dict[str, float]:
    """``winsorize_series(method="mad")``：中位数 ± 3·MAD，MAD 为 0 时不裁剪。"""
    finite = [v for v in values.values() if math.isfinite(v)]
    if not finite:
        return dict(values)
    median = statistics.median(finite)
    mad = statistics.median([abs(v - median) for v in finite])
    if mad == 0:
        return dict(values)
    return _clip(values, median - MAD_K * mad, median + MAD_K * mad)


def utility_winsorize(values: Mapping[str, float]) -> dict[str, float]:
    """``factor_math.winsorize``：中位数 ± 3·MAD 裁剪，MAD 为 0 时裁成中位数。"""
    finite = [v for v in values.values() if math.isfinite(v)]
    if not finite:
        return dict(values)
    median = statistics.median(finite)
    mad = statistics.median([abs(v - median) for v in finite])
    return _clip(values, median - MAD_K * mad, median + MAD_K * mad)


def residualize(
    y: Mapping[str, float],
    x: Mapping[str, float],
    *,
    min_obs: int = MIN_NEUTRAL_OBS,
) -> dict[str, float]:
    """对单个 x 做截面 OLS（含截距），返回 y 的残差。

    样本是 y 与 x 都存在且有限的代码。样本数少于 ``min_obs`` 时抛错，不回退为未中性化的 y。
    """
    keys = sorted(k for k in y if k in x and math.isfinite(y[k]) and math.isfinite(x[k]))
    if len(keys) < min_obs:
        raise FeatureLookupError(f"中性化有效样本 {len(keys)} 少于 {min_obs}，不产出")
    y_vec = np.array([y[k] for k in keys], dtype=float)
    x_mat = sm.add_constant(np.array([x[k] for k in keys], dtype=float), has_constant="add")
    fitted = sm.OLS(y_vec, x_mat).fit().predict(x_mat)
    residual = y_vec - fitted
    return {key: float(value) for key, value in zip(keys, residual, strict=True)}


def _clip(values: Mapping[str, float], lower: float, upper: float) -> dict[str, float]:
    # NaN 不被 min/max 改变，与 pandas clip 保留缺失一致。
    return {k: min(max(v, lower), upper) if math.isfinite(v) else v for k, v in values.items()}


def weighted_zscore(
    values: Mapping[str, float],
    weight: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """``factor_math.normalize``：缺失先填加权均值，再做未加权 z-score（ddof=0）。

    精确复现旧仓语义：

    1. 有效值（有限）为空 → 返回同键 0 序列。
    2. 加权均值：``weight`` 非空且与有效值的交集中权重和>0 时，对该交集做
       ``sum(v · w/sum(w))``；否则退化为有效值的等权均值。
    3. NaN 键填补为该均值（参与后续 std，与旧仓 ``a_new.loc[isna]=mean`` 一致）。
    4. 标准差用**未加权总体** ``np.std(ddof=0)``，且**含刚填补的均值键**——
       注意 std 不是市值加权的，加权只用在均值。这是旧仓的真实（未必最优）口径。
    5. std 为 0 或 NaN → 返回同键 0 序列。
    6. 返回 ``(v - mean) / std``。原为 NaN 的键经填补后不再是 NaN（除非 std=0 走 0 序列）。
    """
    finite_keys = [k for k, v in values.items() if math.isfinite(v)]
    if not finite_keys:
        return dict.fromkeys(values, 0.0)
    mean = _weighted_mean(values, weight, finite_keys)
    # NaN 键填补为均值（含原本就无该键的情况不存在——只填已有的 NaN 键）。
    filled = {k: (v if math.isfinite(v) else mean) for k, v in values.items()}
    arr = list(filled.values())
    std = math.sqrt(sum((x - _mean(arr)) ** 2 for x in arr) / len(arr)) if arr else float("nan")
    if not math.isfinite(std) or std == 0:
        return dict.fromkeys(values, 0.0)
    return {k: (filled[k] - mean) / std for k in values}


def industry_median_fill(
    values: Mapping[str, float],
    industry: Mapping[str, str],
) -> dict[str, float]:
    """``descriptor_process`` 中行业中位数填补：NaN 键填同行业有限值的中位数。

    仅在 ``industry`` 非空时填补。同行业无有限值或该股无行业映射时，保持 NaN。
    返回的键集合与 ``values`` 一致（reindex 到 industry.index 的扩展在 panel 层做，
    不在此纯函数里——纯函数只处理传入的键）。
    """
    if not industry:
        return dict(values)
    # 按行业分组收集有限值。
    by_industry: dict[str, list[float]] = {}
    for k, ind in industry.items():
        if k in values and math.isfinite(values[k]):
            by_industry.setdefault(ind, []).append(values[k])
    median_by_industry = {ind: statistics.median(vs) for ind, vs in by_industry.items() if vs}
    out = {}
    for k, v in values.items():
        if math.isfinite(v):
            out[k] = v
        else:
            ind_code: str | None = industry.get(k)
            med = median_by_industry.get(ind_code) if ind_code is not None else None
            out[k] = med if med is not None else v
    return out


def descriptor_pipeline(
    values: Mapping[str, float],
    industry: Mapping[str, str] | None = None,
    weight: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """``descriptor_process`` 完整链：工具去极值 → 行业中位数填补 → 市值加权 z-score。

    顺序固定，是 exposure 迁移前后数值零差异的关键路径。全空输入返回 0 序列（与旧仓一致）。
    注意：旧仓先 reindex 到 industry_map.index 再处理；本纯函数假设调用方已对齐键集合。
    """
    finite = [v for v in values.values() if math.isfinite(v)]
    if not finite:
        return dict.fromkeys(values, 0.0)
    step1 = utility_winsorize(values)
    step2 = industry_median_fill(step1, industry) if industry else step1
    return weighted_zscore(step2, weight)


def l3_integrate(
    descriptors: Mapping[str, Mapping[str, float]],
    industry: Mapping[str, str] | None = None,
    weight: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """``l3integrate``：各 descriptor 经 descriptor_pipeline 后**等权平均**合成二级因子。

    ``descriptors`` 为 {descriptor名: {股票: 原始值}}。逐 descriptor 做 descriptor_pipeline，
    再按股票对齐求均值（除以 descriptor 个数）。键集合取各 descriptor 处理后键的并集——
    因 descriptor_pipeline 后 NaN 多被填补/标准化，实际键趋于一致；缺失某 descriptor 的键
    按存在的 descriptor 均值（与旧仓 ftr 逐 descriptor 累加后除总数不同，旧仓是简单 sum/len，
    缺失键在 sum 时按 0 计入。这里复现旧仓：缺失键按 0 计入求和后除以总数）。
    """
    if not descriptors:
        return {}
    processed = {name: descriptor_pipeline(vals, industry, weight) for name, vals in descriptors.items()}
    all_keys: set[str] = set()
    for vals in processed.values():
        all_keys.update(vals.keys())
    n = len(processed)
    out = {}
    for k in all_keys:
        # 缺失键按 0 计入（复现旧仓 sum 时缺键不产生贡献、最后统一除总数）。
        total = sum(vals.get(k, 0.0) if math.isfinite(vals.get(k, float("nan"))) else 0.0 for vals in processed.values())
        out[k] = total / n
    return out


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def _weighted_mean(
    values: Mapping[str, float],
    weight: Mapping[str, float] | None,
    finite_keys: list[str],
) -> float:
    """加权均值：weight 与有效值交集权重和>0 时加权，否则等权。复现 factor_math.normalize。"""
    if weight:
        # 交集：值有限且权重有限的键。
        pairs = [(values[k], weight[k]) for k in finite_keys if k in weight and math.isfinite(weight[k])]
        wsum = sum(w for _, w in pairs)
        if pairs and wsum != 0:
            return sum(v * (w / wsum) for v, w in pairs)
    # 等权均值（仅有限值）。
    finite_vals = [values[k] for k in finite_keys]
    return sum(finite_vals) / len(finite_vals)
