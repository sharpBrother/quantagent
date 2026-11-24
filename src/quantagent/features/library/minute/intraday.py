"""分钟行情的单日统计，复现旧仓 ``factors/factor_min.py`` 的四个日内因子。

旧实现的数据准备（``get_min_data``，factor_min.py:863-886）与这里的对应：

- 收益率是 ``close.pct_change()``，每只股票每个交易日单独计算。首根没有前值，被
  ``dropna`` 去掉，所以收益率不跨日。这里只在当日内取相邻两根。
- 每日根数不过滤。源端有 241 根（含 09:30），旧代码同样保留。旧代码注释写的 239 根与
  数据不符，以数据为准。
- 零成交的 bar 保留，收益率为 0。
- 旧代码的 ``float_mv`` 缺失会丢整日。这里不读 ``float_mv``，口径差异在面板层报告。

pandas 的数值细节照旧复现：``kurt`` 用 Fisher 偏差修正公式，样本数小于 4 为缺失；``corr``
按成对剔除缺失，样本少于 2 或方差为 0 时为缺失；``std`` 用 ddof=1。
与旧表不同的两处假 0 已裁定为缺失：``kurt`` 经 pandas 判为零方差（见 ``is_pandas_zero_variance``），
比率的上行或下行不超过 1 根（见 ``_ratio``）。

"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

# 样本数门槛：kurt 的 Fisher 修正分母含 (n-2)(n-3)，故至少 4 个；std 与 corr 至少 2 个。
_MIN_KURT_N = 4
_MIN_PAIR_N = 2
# pandas 抑制浮点误差的阈值，与 pandas/core/nanops.py:1578-1583 的 _zero_out_fperr 一致。
# 绝对值小于它的分母按 0 处理，pandas 因此对近零方差的序列返回 0。
_FPERR_EPS = 1e-14


@dataclass(frozen=True)
class MinuteDayStats:
    """一只股票一个交易日的四个日值。``None`` 表示该日不产值。"""

    corr_vrlag: float | None
    real_kurt: float | None
    ratio_realupvar: float | None
    ratio_realdownvar: float | None


def minute_day_stats(closes: Sequence[float], volumes: Sequence[float]) -> MinuteDayStats:
    """``closes`` 与 ``volumes`` 是同一股票同一交易日、按 trade_time 升序的 bar。"""
    if len(closes) != len(volumes):
        raise ValueError("closes 与 volumes 长度不一致")
    for price in closes:
        # 旧代码对零价会得到 inf 并静默跳过，这里直接失败，不把异常数据当缺失。
        if not math.isfinite(price) or price <= 0:
            raise ValueError(f"分钟收盘价非正或非有限: {price}")
    for volume in volumes:
        if not math.isfinite(volume) or volume < 0:
            raise ValueError(f"分钟成交量为负或非有限: {volume}")
    rets = [closes[i + 1] / closes[i] - 1.0 for i in range(len(closes) - 1)]
    return MinuteDayStats(
        corr_vrlag=_corr_vrlag(volumes, rets),
        real_kurt=_real_kurt(rets),
        ratio_realupvar=_ratio(rets, side="up"),
        ratio_realdownvar=_ratio(rets, side="down"),
    )


def _corr_vrlag(volumes: Sequence[float], rets: Sequence[float]) -> float | None:
    # 旧代码为 volume.corr(pctchg.shift(1))。第 j 根的成交量与第 j-1 根的收益率配对，
    # 所以配对为 (volumes[2:], rets[:-1])，两者长度都是 N-2。
    return _pearson(volumes[2:], rets[:-1])


def is_pandas_zero_variance(rets: Sequence[float]) -> bool:
    """收益序列经 pandas ``nankurt`` 判为零方差：分母经阈值置零后为 0，pandas 返回 0。

    样本数不足 4 时 pandas 返回 NaN，不属于本判定，返回 False。
    """
    if len(rets) < _MIN_KURT_N:
        return False
    return _kurt_parts(rets)[1] == 0


def _real_kurt(rets: Sequence[float]) -> float | None:
    n = len(rets)
    if n < _MIN_KURT_N:
        return None
    numerator, denominator, adj = _kurt_parts(rets)
    if denominator == 0:
        # 分母低于 pandas 的浮点阈值时 pandas 返回 0（nanops.py:1369-1370），旧表因此存假 0。
        # 典型情形是当日只有 ±1e-6 量级的非零收益，pandas 视为零方差。负责人 2026-11-24 裁定记为缺失。
        return None
    return numerator / denominator - adj


def _kurt_parts(rets: Sequence[float]) -> tuple[float, float, float]:
    """返回 (numerator, denominator, adj)，公式与 pandas ``nankurt`` 相同。

    已知差异：这里的求和是 Python 顺序求和，pandas 用 numpy 成对求和，两者的 m2 有 1e-16 相对量级
    的差。只有分母落在 1e-14 阈值的相对 1e-15 邻域内时判定才可能不同。集成测试对 9 个截面日的
    全部股票逐一用 pandas 复核，未出现分歧。

    出处（pandas 2.3.3，``pandas/core/nanops.py``）：
    - 分母 ``(count - 2) * (count - 3) * m2**2``：第 1355 行；分子 ``count * (count + 1) * (count - 1) * m4``：
      第 1354 行；修正项 ``adj``：第 1353 行。
    - 分子与分母各自经 ``_zero_out_fperr`` 置零：第 1361-1362 行。
    - 分母为 0 时返回 0：第 1369-1370 行。
    - 阈值 ``1e-14`` 与 ``_zero_out_fperr`` 的定义：第 1578-1583 行。
    """
    n = len(rets)
    mean = sum(rets) / n
    dev2 = [(x - mean) ** 2 for x in rets]
    m2 = sum(dev2)
    m4 = sum(d * d for d in dev2)
    adj = 3 * (n - 1) ** 2 / ((n - 2) * (n - 3))
    numerator = _zero_fperr(n * (n + 1) * (n - 1) * m4)
    denominator = _zero_fperr((n - 2) * (n - 3) * m2**2)
    return numerator, denominator, adj


def _ratio(rets: Sequence[float], *, side: Literal["up", "down"]) -> float | None:
    rv = _sample_std(rets)
    if rv is None or rv <= 0:
        # 旧代码 ``if rv > 0`` 不成立时不产值。
        return None
    picked = [x for x in rets if (x > 0 if side == "up" else x < 0)]
    if len(picked) <= 1:
        # 旧代码 real_upvar/real_downvar 在不超过 1 根时返回 0，比率随之为 0。这是假 0，
        # 不是真实的零波动。负责人 2026-11-22 裁定：记为缺失，不产该日值。
        return None
    upvar = _sample_std(picked)
    if upvar is None:
        return None
    return upvar / rv


def _sample_std(xs: Sequence[float]) -> float | None:
    n = len(xs)
    if n < _MIN_PAIR_N:
        return None
    mean = sum(xs) / n
    return math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1))


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    if n != len(ys):
        raise ValueError("pearson 输入长度不一致")
    if n < _MIN_PAIR_N:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    cov = sum(a * b for a, b in zip(dx, dy, strict=True)) / (n - 1)
    sx = math.sqrt(sum(a * a for a in dx) / (n - 1))
    sy = math.sqrt(sum(b * b for b in dy) / (n - 1))
    if sx == 0 or sy == 0:
        return None
    # 与 numpy.corrcoef 一样截断到 [-1, 1]，浮点舍入不能越界。
    return max(-1.0, min(1.0, cov / sx / sy))


def _zero_fperr(value: float) -> float:
    # pandas 的 _zero_out_fperr：绝对值小于 _FPERR_EPS 的数按 0 处理，抑制浮点误差。
    return 0.0 if abs(value) < _FPERR_EPS else value
