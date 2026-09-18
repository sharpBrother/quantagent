"""成员区间命中。调用方不要手写 valid_from / valid_to 条件。

闭区间：``valid_from <= dt`` 且 ``(valid_to 空或 valid_to >= dt)``。
对齐已裁定的 Wind ``S_CON_INDATE`` / ``OUTDATE`` 对 ``as_of`` 切片，
不是半开的 ``valid_to > dt``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date


def interval_contains(*, valid_from: date, valid_to: date | None, dt: date) -> bool:
    if valid_from > dt:
        return False
    if valid_to is None:
        return True
    return valid_to >= dt
