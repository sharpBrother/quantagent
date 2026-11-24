"""``pf_single_*_5_mean_neg`` 的身份与五日均值口径。

旧消费端（``alpha_factory/factor_loader.py`` 的 ``_load_performance_factor_single`` 与
``performance_factor_single.aggregate_factor_values``）的口径：

- 窗口是截至前一开市日的最近 5 个开市日（交易日历上的日子，不是个股有值的日子）。
- 每只股票对窗口内有值的日子取 ``mean``，pandas 的 mean 跳过缺失。没有最少样本数限制，
  一天有值就产出。窗口内没有任何值则不产出。
- 方向 ``direction = -1`` 作用在均值上，即 ``SIGN * mean``。

本模块的 ``event_dt`` 取窗口的最后一天 d。旧消费端在 d 的下一个开市日使用同一个值，
两者数值相同，只是日期标注不同。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from quantagent.platform.identity import digest_json

if TYPE_CHECKING:
    from collections.abc import Sequence

WINDOW_OPEN_DAYS = 5
SIGN = -1.0
DEFINITION_VERSION = "v1"


@dataclass(frozen=True)
class MinuteFactorSpec:
    """一个 Current-20 分钟因子的身份。``stat`` 指向 ``MinuteDayStats`` 的字段名。"""

    feature_id: str
    stat: str
    legacy_name: str
    param_hash: str


def _spec(legacy_name: str, stat: str) -> MinuteFactorSpec:
    feature_id = f"pf_single_{legacy_name}_{WINDOW_OPEN_DAYS}_mean_neg"
    params = {
        "window": WINDOW_OPEN_DAYS,
        "demind": "mean",
        "sign": "-1",
        "day_stat": legacy_name,
    }
    return MinuteFactorSpec(
        feature_id=feature_id,
        stat=stat,
        legacy_name=legacy_name,
        param_hash=digest_json(params),
    )


SPECS: tuple[MinuteFactorSpec, ...] = (
    _spec("corr_vrlag", "corr_vrlag"),
    _spec("real_kurt", "real_kurt"),
    _spec("ratio_realupvar", "ratio_realupvar"),
    _spec("ratio_realdownvar", "ratio_realdownvar"),
)


def window_mean(values: Sequence[float | None]) -> float | None:
    """窗口内有值的日子取均值，缺失跳过。全部缺失则为 ``None``。"""
    valid = [value for value in values if value is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)
