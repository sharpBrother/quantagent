"""物化入口的选取逻辑：不传代码时按截面日 all_a 成员；``feature_ids`` 只写指定因子。

PG 连接、开市日历与写入都用替身，只验证本仓新增的选取与过滤。
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any, ClassVar, cast

import pytest

from quantagent.cli import cutamp_materialize as cutamp_mod
from quantagent.cli import minute_factors_materialize as minute_mod
from quantagent.domain.calendar.types import CalendarDay


class _FakeConn:
    def close(self) -> None:
        return None


class _FakePriceRepo:
    requested: ClassVar[list[tuple[str, ...]]] = []

    def __init__(self, _conn: object) -> None:
        pass

    def list_prices(
        self, *, as_of: date, start: date, end: date, wind_codes: tuple[str, ...]
    ) -> tuple[()]:
        _FakePriceRepo.requested.append(tuple(wind_codes))
        return ()


def _row(asset_id: str, event_dt: date, feature_id: str = "f") -> Any:
    return SimpleNamespace(
        asset_id=asset_id,
        event_dt=event_dt,
        feature_id=feature_id,
        value=1.0,
        knowledge_dt=event_dt,
        pit_grade="A",
    )


def _paths(tmp_path: Any) -> Any:
    return cast("Any", SimpleNamespace(lake=tmp_path / "lake", runs=tmp_path / "runs"))


@pytest.mark.unit
def test_cutamp_without_codes_reads_union_of_all_a_and_keeps_only_members(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    day1, day2 = date(2026, 1, 5), date(2026, 1, 6)
    members = {day1: frozenset({"A", "B"}), day2: frozenset({"B"})}
    written: list[Any] = []
    _FakePriceRepo.requested = []

    monkeypatch.setattr(cutamp_mod, "connect", lambda *_a, **_k: _FakeConn())
    monkeypatch.setattr(cutamp_mod, "_open_days", lambda *_a, **_k: (day1, day2))
    monkeypatch.setattr(cutamp_mod, "all_a_members_by_day", lambda *_a, **_k: members)
    monkeypatch.setattr(cutamp_mod, "PostgresDailyPriceRepository", _FakePriceRepo)
    # 替身产出 A、B 在两天的行；A 在 day2 不是成员，必须被丢弃。
    monkeypatch.setattr(
        cutamp_mod,
        "build_cutamp_values",
        lambda *_a, **_k: (
            _row("A", day1),
            _row("B", day1),
            _row("A", day2),
            _row("B", day2),
        ),
    )

    def _capture(rows: Any, _dest: object) -> dict[str, int]:
        written.extend(rows)
        return {"n_files": 1, "nbytes": 1}

    monkeypatch.setattr(cutamp_mod, "write_feature_values", _capture)

    row_count, _digest = cutamp_mod.materialize_cutamp(
        settings=cast("Any", None),
        paths=_paths(tmp_path),
        start=day1,
        end=day2,
        wind_codes=None,
        as_of=day2,
    )

    assert _FakePriceRepo.requested == [("A", "B")]
    assert [(row.asset_id, row.event_dt) for row in written] == [
        ("A", day1),
        ("B", day1),
        ("B", day2),
    ]
    assert row_count == 3


@pytest.mark.unit
def test_minute_factors_feature_filter_writes_only_requested_features(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    day = date(2026, 1, 5)
    rows = (
        _row("A", day, "pf_single_corr_vrlag_5_mean_neg"),
        _row("A", day, "pf_single_real_kurt_5_mean_neg"),
    )
    written: list[Any] = []

    class _Calendar:
        def __init__(self, _root: object) -> None:
            pass

        def list_days(self, **_k: object) -> tuple[CalendarDay, ...]:
            return (CalendarDay(cal_dt=day, exchange="SSE", is_open=True, prev_trade_dt=None),)

    monkeypatch.setattr(minute_mod, "connect", lambda *_a, **_k: _FakeConn())
    monkeypatch.setattr(minute_mod, "LakeCalendarRepository", _Calendar)
    monkeypatch.setattr(minute_mod, "build_minute_factor_values", lambda *_a, **_k: rows)

    def _capture(got: Any, _dest: object) -> dict[str, int]:
        written.extend(got)
        return {"n_files": 1, "nbytes": 1}

    monkeypatch.setattr(minute_mod, "write_feature_values", _capture)

    row_count, _digest = minute_mod.materialize_minute_factors(
        settings=cast("Any", None),
        paths=_paths(tmp_path),
        start=day,
        end=day,
        as_of=day,
        codes=("A",),
        feature_ids=("pf_single_real_kurt_5_mean_neg",),
    )

    assert [row.feature_id for row in written] == ["pf_single_real_kurt_5_mean_neg"]
    assert row_count == 1


@pytest.mark.unit
def test_minute_factors_empty_feature_filter_is_rejected(tmp_path: Any) -> None:
    with pytest.raises(ValueError, match="feature_ids 为空"):
        minute_mod.materialize_minute_factors(
            settings=cast("Any", None),
            paths=_paths(tmp_path),
            start=date(2026, 1, 5),
            end=date(2026, 1, 5),
            as_of=date(2026, 1, 5),
            codes=("A",),
            feature_ids=(),
        )
