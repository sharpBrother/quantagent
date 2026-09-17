"""可见性规则求解。

适配器只执行这里算出的截止日；SQL 里不得再发明一套 PIT。本切片只实现
``same_day_close``：点事件在业务日收盘后可见，即 ``event_dt <= as_of``。
其余规则 fail-closed，避免半套求解被当成已支持。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.domain.errors import PitUnsupportedError

if TYPE_CHECKING:
    from datetime import date

    from quantagent.contracts.spec import VisibilityContract

_IMPLEMENTED = frozenset({"same_day_close"})


def visible_event_on_or_before(contract: VisibilityContract, *, as_of: date) -> date:
    """可见点事件的最晚 ``event_field`` 日期（含）。"""
    _require_same_day_close(contract)
    return as_of


def is_point_event_visible(
    contract: VisibilityContract,
    *,
    event_dt: date,
    as_of: date,
) -> bool:
    return event_dt <= visible_event_on_or_before(contract, as_of=as_of)


def _require_same_day_close(contract: VisibilityContract) -> None:
    rule = contract.visibility.rule
    if rule not in _IMPLEMENTED:
        raise PitUnsupportedError(f"可见性规则尚未实现: {rule}")
    if contract.temporal_kind != "point_event":
        raise PitUnsupportedError(
            f"same_day_close 目前只支持 point_event，收到 {contract.temporal_kind}"
        )
    if not contract.event_field:
        raise PitUnsupportedError("point_event 缺少 event_field，无法求解")
