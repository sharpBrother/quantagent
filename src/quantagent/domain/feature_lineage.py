"""因子可见日与 PIT 等级。只从输入推导，不接受调用方抬升。"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from quantagent.domain.errors import FeatureLookupError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

_GRADE_RANK = {"A": 0, "B": 1, "C": 2, "D": 3}
# 合法 pit_grade 集合。写入路径校验与血缘推导共用，不另建一份。
PIT_GRADES: frozenset[str] = frozenset(_GRADE_RANK)


def derive_feature_lineage(
    inputs: Sequence[tuple[date, str]],
    *,
    extra_lag_days: int = 0,
) -> tuple[date, str]:
    """``knowledge_dt`` 取输入最晚可见日再加非负延迟；``pit_grade`` 取最差等级。

    ``extra_lag_days`` 只能把可见日推后。负值会让因子早于输入可见，直接拒绝。
    """
    if not inputs:
        raise FeatureLookupError("因子没有输入，不能推导 knowledge_dt")
    if extra_lag_days < 0:
        raise FeatureLookupError("不允许把 knowledge_dt 提前到输入可见日之前")
    unknown = [grade for _, grade in inputs if grade not in _GRADE_RANK]
    if unknown:
        raise FeatureLookupError(f"未知 pit_grade: {unknown[0]}")
    knowledge_dt = max(day for day, _ in inputs)
    if extra_lag_days:
        knowledge_dt = knowledge_dt + timedelta(days=extra_lag_days)
    worst = max(inputs, key=lambda item: _GRADE_RANK[item[1]])[1]
    return knowledge_dt, worst
