"""可见性规则求解。

适配器只执行这里算出的截止列与截止日；SQL 里不得再发明一套 PIT，也不得
把规则名或 ``knowledge_dt`` 写死在 WHERE 里。

``same_day_close`` 与 ``source_field`` 的截止列不同，不能共用
``event_field``：

- ``same_day_close``：点事件在业务日收盘后可见，截止列就是 ``event_field``
  （日历的 ``cal_dt``），``column <= as_of``。
- ``source_field``：可见日来自契约声明的源字段（``visibility.field``），
  **不是** ``event_field``。因子的截面日可以早于可见日，若用 ``event_dt``
  过滤，等于把尚未可知的值当成已可见。

``visible_event_on_or_before`` / ``is_point_event_visible`` 仍只服务
``same_day_close``，避免日历路径被改口径。其余规则 fail-closed。
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from quantagent.domain.errors import PitUnsupportedError

if TYPE_CHECKING:
    from datetime import date

    from quantagent.contracts.spec import VisibilityContract


@dataclass(frozen=True)
class PitFallback:
    """fallback_mode=earliest 的另一支可见日：源字段 + 固定自然日延迟。"""

    column: str
    lag_days: int
    grade: str


@dataclass(frozen=True)
class PitCutoff:
    column: str
    on_or_before: date
    rule: str
    grade: str
    # 主截止列是 timestamp；读取路径必须按 ::date 比较，否则当天带时刻的记录会被漏掉。
    date_only: bool = False
    fallback: PitFallback | None = None


@dataclass(frozen=True)
class RowPit:
    """逐行求解结果：较早可见的那一支决定日期与等级。"""

    visible_on: date | None
    grade: str | None

    def is_visible(self, *, as_of: date) -> bool:
        return self.visible_on is not None and self.visible_on <= as_of


def pit_cutoff(contract: VisibilityContract, *, as_of: date) -> PitCutoff:
    """给定契约与 ``as_of``，算出读取时应执行的截止列与截止日。"""
    if contract.visibility.fallback is not None:
        if contract.visibility.fallback_mode != "earliest":
            raise PitUnsupportedError("source_field fallback 尚未实现，拒绝半套求解")
        return _earliest_cutoff(contract, as_of=as_of)
    rule = contract.visibility.rule
    grade = contract.visibility.grade
    if rule == "same_day_close":
        return PitCutoff(
            column=_same_day_close_column(contract),
            on_or_before=as_of,
            rule=rule,
            grade=grade,
            date_only=contract.visibility.date_only,
        )
    if rule == "source_field":
        # 严格截止：截止列是日期，``field < as_of`` 与 ``field <= as_of - 1 天`` 等价。
        # 截止列若是时间戳，这个等价不成立，遇到时再扩展，现在不做。
        on_or_before = as_of - timedelta(days=1) if contract.visibility.strict else as_of
        return PitCutoff(
            column=_source_field_column(contract),
            on_or_before=on_or_before,
            rule=rule,
            grade=grade,
            date_only=contract.visibility.date_only,
        )
    raise PitUnsupportedError(f"可见性规则尚未实现: {rule}")


def _earliest_cutoff(contract: VisibilityContract, *, as_of: date) -> PitCutoff:
    spec = contract.visibility
    fallback = spec.fallback
    if fallback is None or fallback.rule != "fixed_lag" or not fallback.field:
        raise PitUnsupportedError("fallback_mode=earliest 缺少可求解的 fixed_lag")
    if fallback.lag_n is None or fallback.lag_unit != "calendar_day":
        raise PitUnsupportedError("fallback_mode=earliest 只支持按自然日固定延迟")
    return PitCutoff(
        column=_source_field_column(contract),
        on_or_before=as_of,
        rule=spec.rule,
        grade=spec.grade,
        date_only=spec.date_only,
        fallback=PitFallback(
            column=fallback.field,
            lag_days=fallback.lag_n,
            grade=fallback.grade,
        ),
    )


def resolve_row_visibility(
    cutoff: PitCutoff,
    *,
    primary: date | None,
    fallback: date | None,
) -> RowPit:
    """逐行取主字段日期与 fallback 推断日中较早者，并保留可见日来源的等级。"""
    if cutoff.fallback is None:
        if primary is None:
            return RowPit(visible_on=None, grade=None)
        return RowPit(visible_on=primary, grade=cutoff.grade)
    candidates: list[tuple[date, str]] = []
    if primary is not None:
        candidates.append((primary, cutoff.grade))
    if fallback is not None:
        if fallback.day != monthrange(fallback.year, fallback.month)[1]:
            # 次月 15 日规则只为月末统计期定义；其他日期不得悄悄套用。
            raise PitUnsupportedError(f"fallback 锚点不是月末，拒绝推断可见日: {fallback}")
        candidates.append(
            (fallback + timedelta(days=cutoff.fallback.lag_days), cutoff.fallback.grade)
        )
    if not candidates:
        return RowPit(visible_on=None, grade=None)
    return RowPit(*min(candidates, key=lambda item: (item[0], item[1])))


def visible_event_on_or_before(contract: VisibilityContract, *, as_of: date) -> date:
    """可见点事件的最晚 ``event_field`` 日期（含）。仅 ``same_day_close``。"""
    if contract.visibility.rule == "source_field":
        # 旧接口按 event_field 截止；source_field 若走这里会把截面日当成可见日。
        raise PitUnsupportedError("source_field 不能把 event_field 当可见日；请用 pit_cutoff")
    _same_day_close_column(contract)
    return as_of


def is_point_event_visible(
    contract: VisibilityContract,
    *,
    event_dt: date,
    as_of: date,
) -> bool:
    return event_dt <= visible_event_on_or_before(contract, as_of=as_of)


def is_cutoff_visible(*, value: date, cutoff: PitCutoff) -> bool:
    return value <= cutoff.on_or_before


def _same_day_close_column(contract: VisibilityContract) -> str:
    rule = contract.visibility.rule
    if rule != "same_day_close":
        raise PitUnsupportedError(f"可见性规则尚未实现: {rule}")
    if contract.temporal_kind != "point_event":
        raise PitUnsupportedError(
            f"same_day_close 目前只支持 point_event，收到 {contract.temporal_kind}"
        )
    if not contract.event_field:
        raise PitUnsupportedError("point_event 缺少 event_field，无法求解")
    return contract.event_field


def _source_field_column(contract: VisibilityContract) -> str:
    field = contract.visibility.field
    if not field:
        raise PitUnsupportedError("source_field 缺少 visibility.field，无法求解")
    return field
