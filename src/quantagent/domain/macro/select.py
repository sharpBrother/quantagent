"""宏观序列的版本选择：某个截止日能看到的是哪一版。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.domain.errors import InvalidQueryError, MacroLookupError
from quantagent.domain.macro.types import MacroObservation

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

    from quantagent.domain.macro.types import MacroVersion


def select_visible_versions(
    versions: Iterable[MacroVersion],
    *,
    start: date,
    end: date,
    visible_on_or_before: date,
    pit_grade: str,
) -> tuple[MacroObservation, ...]:
    """每个 ``(series_id, observation_date)`` 取截止日当天仍生效的那一版。

    生效指 ``visible_from <= 截止日`` 且 ``visible_to`` 为空或不早于截止日。
    只按 ``visible_from`` 取最大会把截止日之前已被源端撤下的观测当成可见。
    同一观测有两版同时生效说明源数据或映射有错，fail-closed，不挑一版。
    """
    if start > end:
        raise InvalidQueryError("start 晚于 end")
    chosen: dict[tuple[str, date], MacroVersion] = {}
    for version in versions:
        if not start <= version.observation_date <= end:
            continue
        if version.visible_from > visible_on_or_before:
            continue
        if version.visible_to is not None and version.visible_to < visible_on_or_before:
            continue
        key = (version.series_id, version.observation_date)
        if key in chosen:
            raise MacroLookupError(
                f"宏观序列同一观测有多个生效版本: {version.series_id} "
                f"{version.observation_date.isoformat()}"
            )
        chosen[key] = version
    return tuple(
        MacroObservation(
            series_id=version.series_id,
            observation_date=version.observation_date,
            value=version.value,
            knowledge_dt=version.visible_from,
            pit_grade=pit_grade,
        )
        for _key, version in sorted(chosen.items())
    )
