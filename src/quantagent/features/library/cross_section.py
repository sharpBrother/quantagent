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
