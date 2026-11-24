"""UMR 框架的通用计算：风险系数的滚动偏离与半衰期加权求和。

``tr_umr`` 与 ``abso_umr`` 共用。这里只做数值计算，不读输入、不推导可见日。
旧仓 ``guosen_umr.py`` 的 ``_rolling_risk_coef`` 与 ``_calc_umr`` 是这两段的来源。
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

from quantagent.domain.errors import FeatureLookupError

if TYPE_CHECKING:
    from collections.abc import Sequence


def risk_coef(values: Sequence[float], *, risk_window: int) -> list[float]:
    """``rolling(risk_window, min_periods=risk_window).mean() - values``。

    窗口里有非有限值就是 NaN。缺口不补 0，也不用前值。
    """
    coef = [math.nan] * len(values)
    for end in range(risk_window - 1, len(values)):
        window = values[end - risk_window + 1 : end + 1]
        if any(not math.isfinite(item) for item in window):
            continue
        mean = float(np.mean(np.asarray(window, dtype=np.float64)))
        coef[end] = mean - window[-1]
    return coef


def weighted_umr(
    risk_tail: Sequence[float],
    excess_tail: Sequence[float],
    *,
    ret_window: int,
    half_life: int,
    sign: float,
) -> float | None:
    """对最后 ``ret_window`` 日的风险系数与超额收益做半衰期加权求和。

    逐位复制旧仓 ``get_exp_weight``，最新一天权重最大。
    v2 起（负责人 2026-11-22 裁定），任一风险系数或超额收益不是有限值，整个截面不产值，
    不再用 nansum 跳过缺失项。旧仓 nansum 会让缺失项按 0 贡献，违反 AGENTS.md §7.5。
    """
    exp_wt = np.asarray([0.5 ** (1 / half_life)] * ret_window) ** np.arange(ret_window)
    weights = exp_wt[::-1] / np.sum(exp_wt)
    if not all(math.isfinite(item) for item in risk_tail) or not all(
        math.isfinite(item) for item in excess_tail
    ):
        return None
    products = (
        weights
        * np.asarray(risk_tail, dtype=np.float64)
        * np.asarray(excess_tail, dtype=np.float64)
    )
    total = float(np.sum(products))
    signed = sign * total
    if not math.isfinite(signed):
        raise FeatureLookupError("UMR 结果不是有限值")
    return signed
