"""Current-20 第二批分钟因子的日值：``corr_vrlaglarge``、``core_up``、``core_down``。

旧实现（``pycharm_workspace/factors/factor_min.py``）：

- ``corr_vrlaglarge``（637-649 行）：按分钟成交量降序取前 ``round(tlen / 3)`` 根，在这些根上算
  ``volume`` 与 ``pctchg.shift(1)`` 的相关（646 行）。降序排序是 ``Series.sort_values(ascending=False)``，
  并列顺序由 quicksort 决定，用 ``legacy_descending_order`` 复现。
- ``core_up``、``core_down``（651-687 行）：把分钟收益的 0 基下标记作横坐标，对上涨（下跌）的分钟收益
  算 ``Σ 下标·r / sqrt(Σ r²)``，分母为 0 时缺失。

数据准备与第一批相同（见 ``intraday.py`` 模块说明）：每只股票每日做 ``pct_change`` 后 ``dropna``，
首根没有前值被去掉。因此参与计算的是第 2 至第 N 根，即 0 基下标 1..N-1，``tlen = N - 1``。
``core`` 的 ``pctchg.index = range(1, n + 1)`` 与 0 基分钟下标一一对应，所以这里直接用 0 基下标。
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Literal

from quantagent.features.library._legacy_sort import legacy_descending_order
from quantagent.features.library.minute.intraday import _pearson
from quantagent.platform.identity import digest_json

if TYPE_CHECKING:
    from collections.abc import Sequence

# pxret21 中性化的身份参数。源端为 ASHAREEODPRICES.S_DQ_ADJCLOSE，窗口 21 个开市日价格点。
# 口径见 features/library/cross_section.py 与 features/panel/minute_2b.py。
_NEUTRALIZER_PARAMS = {
    "factor": "ASHAREEODPRICES.S_DQ_ADJCLOSE",
    "demind": "pctchg",
    "window": 21,
    "direction": "1",
    "winsor": "utility",
    "min_obs": 20,
    "intercept": True,
    "y_winsor": "mad",
    "k": "3",
}

# 一根 bar 没有收益，两根才有第一个收益。
_MIN_BARS = 2
# 第一根保留行（0 基下标 1）的 shift(1) 为缺失，第一个有 shift(1) 值的下标是 2。
_FIRST_BAR_WITH_PREV_RETURN = 2

# 参数指纹：窗口、聚合、方向、日值名与中性化口径。任一变化即是新身份（AGENTS.md §7.8）。
PARAM_HASHES: dict[str, str] = {
    "pf_single_corr_vrlaglarge_5_mean_neg": digest_json(
        {"window": 5, "demind": "mean", "sign": "-1", "day_stat": "corr_vrlaglarge"}
    ),
    "pf_single_core_up_20_mean_pos_neut_pxret21": digest_json(
        {
            "window": 20,
            "demind": "mean",
            "sign": "1",
            "day_stat": "core_up",
            "neutralizer": _NEUTRALIZER_PARAMS,
        }
    ),
    "pf_single_core_down_20_mean_neg_neut_pxret21": digest_json(
        {
            "window": 20,
            "demind": "mean",
            "sign": "-1",
            "day_stat": "core_down",
            "neutralizer": _NEUTRALIZER_PARAMS,
        }
    ),
}


def minute_day_2b(
    closes: Sequence[float], volumes: Sequence[float]
) -> tuple[float | None, float | None, float | None]:
    """返回 ``(corr_vrlaglarge, core_up, core_down)`` 的日值，缺失为 ``None``。

    ``closes`` 与 ``volumes`` 是同一股票同一交易日、按 trade_time 升序的 bar。
    """
    if len(closes) != len(volumes):
        raise ValueError("closes 与 volumes 长度不一致")
    _validate(closes, volumes)
    if len(closes) < _MIN_BARS:
        # 不足两根就没有任何收益，三个日值都缺失。
        return None, None, None
    ret = _bar_returns(closes)
    return (
        _corr_vrlaglarge(volumes, ret),
        _core(ret, side="up"),
        _core(ret, side="down"),
    )


def _validate(closes: Sequence[float], volumes: Sequence[float]) -> None:
    for price in closes:
        # 与第一批相同：零价或非有限价直接失败，不把异常数据当缺失。
        if not math.isfinite(price) or price <= 0:
            raise ValueError(f"分钟收盘价非正或非有限: {price}")
    for volume in volumes:
        if not math.isfinite(volume) or volume < 0:
            raise ValueError(f"分钟成交量为负或非有限: {volume}")


def _bar_returns(closes: Sequence[float]) -> list[float]:
    """``ret[j - 1]`` 是第 j 根（0 基）相对前一根的收益，即 ``pct_change`` 在第 j 根的值。"""
    return [closes[j] / closes[j - 1] - 1.0 for j in range(1, len(closes))]


def _corr_vrlaglarge(volumes: Sequence[float], ret: Sequence[float]) -> float | None:
    tlen = len(volumes) - 1
    # 参与排序的是去掉首根后的成交量，位置 p 对应 0 基分钟下标 p + 1。
    order = legacy_descending_order(list(volumes[1:]))
    top = round(tlen / 3)
    large_bars = [order[i] + 1 for i in range(top)]
    xs: list[float] = []
    ys: list[float] = []
    # 旧代码 pctchg.shift(1) 在第一根保留行上为缺失，成对剔除。第 b 根的 shift(1) 是第 b-1 根的收益。
    for bar in large_bars:
        if bar >= _FIRST_BAR_WITH_PREV_RETURN:
            xs.append(volumes[bar])
            ys.append(ret[bar - 2])
    return _pearson(xs, ys)


def _core(ret: Sequence[float], *, side: Literal["up", "down"]) -> float | None:
    picked = [
        (index + 1, value)
        for index, value in enumerate(ret)
        if (value > 0 if side == "up" else value < 0)
    ]
    denominator = math.sqrt(sum(value * value for _, value in picked))
    if denominator == 0:
        # 旧代码返回 np.nan，不写 0。无上涨或无下跌分钟时分母为 0。
        return None
    numerator = sum(bar * value for bar, value in picked)
    return numerator / denominator
