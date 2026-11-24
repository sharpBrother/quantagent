"""宏观版本选择：截止日当天生效的那一版，撤下的不可见，并列生效 fail-closed。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from quantagent.domain.errors import InvalidQueryError, MacroLookupError
from quantagent.domain.macro import MacroVersion, normalize_series_ids, select_visible_versions


def _v(obs: date, value: str | None, vis_from: date, vis_to: date | None) -> MacroVersion:
    return MacroVersion(
        series_id="us_tips_10y",
        observation_date=obs,
        value=None if value is None else Decimal(value),
        visible_from=vis_from,
        visible_to=vis_to,
    )


_OBS = date(2024, 1, 2)
_REVISIONS = (
    _v(_OBS, "1.70", date(2024, 1, 3), date(2024, 1, 9)),
    _v(_OBS, "1.72", date(2024, 1, 10), None),
)


def _select(
    cutoff: date, versions: tuple[MacroVersion, ...] = _REVISIONS
) -> list[tuple[Decimal | None, date, str]]:
    rows = select_visible_versions(
        versions, start=_OBS, end=_OBS, visible_on_or_before=cutoff, pit_grade="A"
    )
    return [(r.value, r.knowledge_dt, r.pit_grade) for r in rows]


@pytest.mark.unit
def test_returns_version_in_force_at_cutoff_not_latest() -> None:
    assert _select(date(2024, 1, 2)) == []
    assert _select(date(2024, 1, 3)) == [(Decimal("1.70"), date(2024, 1, 3), "A")]
    assert _select(date(2024, 1, 9)) == [(Decimal("1.70"), date(2024, 1, 3), "A")]
    assert _select(date(2024, 1, 10)) == [(Decimal("1.72"), date(2024, 1, 10), "A")]


@pytest.mark.unit
def test_withdrawn_observation_is_invisible_after_withdrawal() -> None:
    withdrawn = (_v(_OBS, "1.70", date(2024, 1, 3), date(2024, 1, 9)),)
    assert _select(date(2024, 1, 5), withdrawn) == [(Decimal("1.70"), date(2024, 1, 3), "A")]
    assert _select(date(2024, 1, 10), withdrawn) == []


@pytest.mark.unit
def test_null_latest_value_stays_missing() -> None:
    versions = (
        _v(_OBS, "1.70", date(2024, 1, 3), date(2024, 1, 9)),
        _v(_OBS, None, date(2024, 1, 10), None),
    )
    assert _select(date(2024, 1, 12), versions) == [(None, date(2024, 1, 10), "A")]


@pytest.mark.unit
def test_overlapping_versions_fail_closed() -> None:
    versions = (
        _v(_OBS, "1.70", date(2024, 1, 3), None),
        _v(_OBS, "1.72", date(2024, 1, 10), None),
    )
    with pytest.raises(MacroLookupError, match="多个生效版本"):
        _select(date(2024, 1, 12), versions)


@pytest.mark.unit
def test_series_ids_must_be_registered_and_unique() -> None:
    assert normalize_series_ids(()) is None
    assert normalize_series_ids(("cn_cgb_10y", "us_ust_10y")) == ("cn_cgb_10y", "us_ust_10y")
    with pytest.raises(InvalidQueryError, match="未登记"):
        normalize_series_ids(("cn_cgb_1y",))
    with pytest.raises(InvalidQueryError, match="重复"):
        normalize_series_ids(("cn_cgb_10y", "cn_cgb_10y"))
