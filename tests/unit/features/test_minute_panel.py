"""分钟因子面板：窗口、缺失、排除日、股票池、血缘与口径守卫。使用内存假仓储，不碰 PG 与 lake。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.errors import EmptyDomainError, FeatureLookupError
from quantagent.features.library.minute.five_day import SPECS
from quantagent.features.library.minute.intraday import minute_day_stats
from quantagent.features.panel.minute import build_minute_factor_values

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

_DATASET = "src.minprice.ashare_minute_bar"
_AS_OF_STAMP = datetime(2026, 1, 1)


def _contract(rule: str = "same_day_close", grade: str = "A") -> VisibilityContract:
    visibility: dict[str, Any] = {
        "rule": rule,
        "grade": grade,
        "rationale": "分钟因子面板测试用的行情可见性规则说明足够长，满足契约最短长度",
    }
    if rule == "fixed_lag":
        visibility.update({"lag_n": 1, "lag_unit": "trading_day"})
    return VisibilityContract.model_validate(
        {
            "dataset": _DATASET,
            "doc_ref": "docs/migration/minute-bar-ingest-plan.md",
            "temporal_kind": "point_event",
            "event_field": "trade_date",
            "visibility": visibility,
            "pit_recoverable": True,
        }
    )


def _fixed(*codes: str) -> Callable[[date], tuple[str, ...]]:
    """每个截面日的股票池都相同。"""
    return lambda _day: codes


@dataclass
class _Table:
    rows: list[dict[str, Any]]

    @property
    def num_rows(self) -> int:
        return len(self.rows)

    def to_pylist(self) -> list[dict[str, Any]]:
        return list(self.rows)


class _FakeRepo:
    """按日返回预置的分钟行，并记录调用参数。``excluded`` 给出每日的排除集。"""

    def __init__(
        self,
        bars: dict[date, dict[str, list[tuple[float, float]]]],
        excluded: dict[date, frozenset[str]] | None = None,
    ) -> None:
        self._bars = bars
        self._excluded = excluded or {}
        self.calls: list[dict[str, Any]] = []

    def excluded_codes(self, *, as_of: date, day: date) -> frozenset[str]:
        return self._excluded.get(day, frozenset())

    def scan_window(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        codes: Any = None,
        columns: Any = None,
    ) -> _Table:
        self.calls.append({"as_of": as_of, "start": start, "end": end, "codes": codes})
        rows: list[dict[str, Any]] = []
        for day in sorted(self._bars):
            if not start <= day <= end:
                continue
            for code, bars in self._bars[day].items():
                if codes is not None and code not in codes:
                    continue
                for minute, (close, vol) in enumerate(bars):
                    stamp = datetime.combine(day, time(9, 31)) + timedelta(minutes=minute)
                    rows.append({"ts_code": code, "trade_time": stamp, "close": close, "vol": vol})
        return _Table(rows)


def _opens(count: int) -> list[date]:
    out: list[date] = []
    day = date(2024, 9, 2)
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def _bars(seed: int) -> list[tuple[float, float]]:
    # 8 根 bar 足以让 corr 与 kurt 有定义，比率在上涨或下跌超过 1 根时有定义。
    closes = [10.0, 10.2, 10.1, 10.4, 10.3, 10.6, 10.5, 10.7 + seed * 0.01]
    vols = [5.0, 1.0, 8.0, 2.0, 9.0, 3.0, 7.0, 4.0 + seed]
    return list(zip(closes, vols, strict=True))


def _expected_mean(
    bars_by_day: Sequence[list[tuple[float, float]] | None], stat: str
) -> float | None:
    values: list[float | None] = []
    for bars in bars_by_day:
        if bars is None:
            values.append(None)
            continue
        day = minute_day_stats([c for c, _ in bars], [v for _, v in bars])
        values.append(getattr(day, stat))
    valid = [value for value in values if value is not None]
    if not valid:
        return None
    return -sum(valid) / len(valid)


@pytest.mark.unit
def test_value_is_negative_five_day_mean_of_daily_stats() -> None:
    opens = _opens(8)
    bars = {day: {"000001.SZ": _bars(i)} for i, day in enumerate(opens)}
    repo = _FakeRepo(bars)
    rows = build_minute_factor_values(
        repo,
        as_of=opens[-1],
        opens=opens,
        start=opens[4],
        end=opens[7],
        contract=_contract(),
        universe_at=_fixed("000001.SZ"),
        computed_at=_AS_OF_STAMP,
        run_id="test",
    )
    by_key = {(row.event_dt, row.feature_id): row for row in rows}
    for event_idx in (4, 5, 6, 7):
        window = [bars[day]["000001.SZ"] for day in opens[event_idx - 4 : event_idx + 1]]
        for spec in SPECS:
            expected = _expected_mean(window, spec.stat)
            row = by_key[(opens[event_idx], spec.feature_id)]
            assert row.value == pytest.approx(expected, rel=1e-12)
            assert row.asset_id == "000001.SZ"
            assert row.asset_class == "stock"
            assert row.param_hash == spec.param_hash


@pytest.mark.unit
def test_window_reads_each_open_day_once_with_as_of() -> None:
    opens = _opens(6)
    repo = _FakeRepo({day: {"000001.SZ": _bars(0)} for day in opens})
    build_minute_factor_values(
        repo,
        as_of=opens[-1],
        opens=opens,
        start=opens[4],
        end=opens[5],
        contract=_contract(),
        universe_at=_fixed("000001.SZ"),
        computed_at=_AS_OF_STAMP,
        run_id="test",
    )
    assert [call["start"] for call in repo.calls] == opens
    assert all(call["as_of"] == opens[-1] for call in repo.calls)
    assert all(call["start"] == call["end"] for call in repo.calls)
    assert all(call["codes"] == ["000001.SZ"] for call in repo.calls)


@pytest.mark.unit
def test_missing_day_is_skipped_not_filled() -> None:
    opens = _opens(6)
    bars = {day: {"000001.SZ": _bars(i)} for i, day in enumerate(opens)}
    # 第 3 天该股没有行。窗口均值只用其余日子，不补 0。
    del bars[opens[3]]["000001.SZ"]
    repo = _FakeRepo(bars)
    rows = build_minute_factor_values(
        repo,
        as_of=opens[-1],
        opens=opens,
        start=opens[4],
        end=opens[4],
        contract=_contract(),
        universe_at=_fixed("000001.SZ"),
        computed_at=_AS_OF_STAMP,
        run_id="test",
    )
    window = [bars[day].get("000001.SZ") for day in opens[0:5]]
    expected = _expected_mean(window, "corr_vrlag")
    row = next(item for item in rows if item.feature_id == SPECS[0].feature_id)
    assert row.value == pytest.approx(expected, rel=1e-12)


@pytest.mark.unit
def test_no_row_when_every_day_in_window_is_missing() -> None:
    # 000002.SZ 只在最早一天有行。对 event_dt=opens[5]，窗口 opens[1..5] 全部缺失，不产行。
    # 对 event_dt=opens[4]，窗口 opens[0..4] 含 opens[0]，应当产行。
    opens = _opens(6)
    bars = {day: {"000001.SZ": _bars(0)} for day in opens}
    bars[opens[0]]["000002.SZ"] = _bars(1)
    repo = _FakeRepo(bars)
    rows = build_minute_factor_values(
        repo,
        as_of=opens[-1],
        opens=opens,
        start=opens[4],
        end=opens[5],
        contract=_contract(),
        universe_at=_fixed("000001.SZ", "000002.SZ"),
        computed_at=_AS_OF_STAMP,
        run_id="test",
    )
    rows_000002 = [row for row in rows if row.asset_id == "000002.SZ"]
    assert {row.event_dt for row in rows_000002} == {opens[4]}


@pytest.mark.unit
def test_ratio_missing_day_excluded_from_mean() -> None:
    # 某天上涨只有 1 根（或下跌只有 1 根），比率日值为缺失，窗口均值只用其余日子。
    opens = _opens(5)
    flat_up = [(10.0, 1.0), (10.0, 1.0), (10.0, 1.0), (10.0, 1.0), (10.1, 1.0), (10.1, 1.0)]
    bars = {day: {"000003.SZ": _bars(i)} for i, day in enumerate(opens)}
    bars[opens[2]] = {"000003.SZ": flat_up}
    repo = _FakeRepo(bars)
    rows = build_minute_factor_values(
        repo,
        as_of=opens[-1],
        opens=opens,
        start=opens[4],
        end=opens[4],
        contract=_contract(),
        universe_at=_fixed("000003.SZ"),
        computed_at=_AS_OF_STAMP,
        run_id="test",
    )
    ratio_spec = next(spec for spec in SPECS if spec.stat == "ratio_realupvar")
    window = [bars[day]["000003.SZ"] for day in opens]
    day_values = [minute_day_stats([c for c, _ in b], [v for _, v in b]) for b in window]
    assert day_values[2].ratio_realupvar is None
    expected = -sum(d.ratio_realupvar for d in day_values if d.ratio_realupvar is not None) / sum(
        1 for d in day_values if d.ratio_realupvar is not None
    )
    row = next(item for item in rows if item.feature_id == ratio_spec.feature_id)
    assert row.value == pytest.approx(expected, rel=1e-12)


@pytest.mark.unit
def test_excluded_day_mean_uses_only_remaining_days() -> None:
    # 000001.SZ 在 opens[2] 被排除：该日没有日值，窗口均值只用其余四天。
    # 000002.SZ 不受影响，窗口五天全部参与。
    opens = _opens(6)
    bars = {day: {"000001.SZ": _bars(0), "000002.SZ": _bars(1)} for day in opens}
    repo = _FakeRepo(bars, excluded={opens[2]: frozenset({"000001.SZ"})})
    rows = build_minute_factor_values(
        repo,
        as_of=opens[-1],
        opens=opens,
        start=opens[4],
        end=opens[4],
        contract=_contract(),
        universe_at=_fixed("000001.SZ", "000002.SZ"),
        computed_at=_AS_OF_STAMP,
        run_id="test",
    )
    spec = SPECS[0]
    got = {row.asset_id: row.value for row in rows if row.feature_id == spec.feature_id}
    window_a = [None if day == opens[2] else bars[day]["000001.SZ"] for day in opens[0:5]]
    window_b = [bars[day]["000002.SZ"] for day in opens[0:5]]
    assert got["000001.SZ"] == pytest.approx(_expected_mean(window_a, spec.stat), rel=1e-12)
    assert got["000002.SZ"] == pytest.approx(_expected_mean(window_b, spec.stat), rel=1e-12)
    # 排除股票在排除日不出现在读取请求中；非排除股票照常请求。
    excluded_call = next(call for call in repo.calls if call["start"] == opens[2])
    assert excluded_call["codes"] == ["000002.SZ"]


@pytest.mark.unit
def test_day_with_every_requested_code_excluded_is_not_read() -> None:
    # 排除后为空：该日不调用读取，所有股票当日无日值，窗口只用其余日子。
    opens = _opens(6)
    bars = {day: {"000001.SZ": _bars(0)} for day in opens}
    repo = _FakeRepo(bars, excluded={opens[2]: frozenset({"000001.SZ"})})
    rows = build_minute_factor_values(
        repo,
        as_of=opens[-1],
        opens=opens,
        start=opens[4],
        end=opens[4],
        contract=_contract(),
        universe_at=_fixed("000001.SZ"),
        computed_at=_AS_OF_STAMP,
        run_id="test",
    )
    assert opens[2] not in {call["start"] for call in repo.calls}
    window = [None if day == opens[2] else bars[day]["000001.SZ"] for day in opens[0:5]]
    row = next(item for item in rows if item.feature_id == SPECS[0].feature_id)
    assert row.value == pytest.approx(_expected_mean(window, SPECS[0].stat), rel=1e-12)


@pytest.mark.unit
def test_output_limited_to_event_day_universe() -> None:
    # 000002.SZ 只在 opens[5] 的截面股票池内。opens[4] 的输出不含它，但 opens[5] 的窗口读取要它。
    opens = _opens(6)
    bars = {day: {"000001.SZ": _bars(0), "000002.SZ": _bars(1)} for day in opens}
    members = {opens[4]: ("000001.SZ",), opens[5]: ("000001.SZ", "000002.SZ")}
    repo = _FakeRepo(bars)
    rows = build_minute_factor_values(
        repo,
        as_of=opens[-1],
        opens=opens,
        start=opens[4],
        end=opens[5],
        contract=_contract(),
        universe_at=lambda day: members[day],
        computed_at=_AS_OF_STAMP,
        run_id="test",
    )
    assert {(row.event_dt, row.asset_id) for row in rows} == (
        {(opens[4], "000001.SZ"), (opens[5], "000001.SZ"), (opens[5], "000002.SZ")}
    )
    # 读取范围是窗口内各截面日股票池的并集：opens[4] 的窗口含 opens[5]，因此要读 000002.SZ；
    # opens[0..3] 的窗口只含 opens[4] 的股票池，不读 000002.SZ。
    codes_by_day = {call["start"]: call["codes"] for call in repo.calls}
    assert "000002.SZ" in codes_by_day[opens[4]]
    assert "000002.SZ" in codes_by_day[opens[5]]
    assert "000002.SZ" not in codes_by_day[opens[0]]


@pytest.mark.unit
def test_lineage_uses_window_days_and_grade() -> None:
    opens = _opens(6)
    repo = _FakeRepo({day: {"000001.SZ": _bars(0)} for day in opens})
    rows = build_minute_factor_values(
        repo,
        as_of=opens[-1],
        opens=opens,
        start=opens[5],
        end=opens[5],
        contract=_contract(grade="A"),
        universe_at=_fixed("000001.SZ"),
        computed_at=_AS_OF_STAMP,
        run_id="test",
    )
    assert rows
    assert all(row.knowledge_dt == opens[5] for row in rows)
    assert all(row.pit_grade == "A" for row in rows)


@pytest.mark.unit
def test_rejects_rule_other_than_same_day_close() -> None:
    opens = _opens(6)
    repo = _FakeRepo({day: {"000001.SZ": _bars(0)} for day in opens})
    with pytest.raises(FeatureLookupError):
        build_minute_factor_values(
            repo,
            as_of=opens[-1],
            opens=opens,
            start=opens[4],
            end=opens[5],
            contract=_contract(rule="fixed_lag"),
            universe_at=_fixed("000001.SZ"),
            computed_at=_AS_OF_STAMP,
            run_id="test",
        )


@pytest.mark.unit
def test_rejects_start_without_four_prior_open_days() -> None:
    opens = _opens(6)
    repo = _FakeRepo({day: {"000001.SZ": _bars(0)} for day in opens})
    with pytest.raises(FeatureLookupError):
        build_minute_factor_values(
            repo,
            as_of=opens[-1],
            opens=opens,
            start=opens[3],
            end=opens[5],
            contract=_contract(),
            universe_at=_fixed("000001.SZ"),
            computed_at=_AS_OF_STAMP,
            run_id="test",
        )


@pytest.mark.unit
def test_rejects_empty_range() -> None:
    opens = _opens(6)
    repo = _FakeRepo({})
    with pytest.raises(EmptyDomainError):
        build_minute_factor_values(
            repo,
            as_of=opens[-1],
            opens=opens,
            start=date(2030, 1, 1),
            end=date(2030, 1, 2),
            contract=_contract(),
            universe_at=_fixed("000001.SZ"),
            computed_at=_AS_OF_STAMP,
            run_id="test",
        )


@pytest.mark.unit
def test_rejects_minute_row_on_other_day() -> None:
    opens = _opens(6)
    repo = _FakeRepo({day: {"000001.SZ": _bars(0)} for day in opens})
    original = repo.scan_window

    def _wrong_day(**kwargs: Any) -> _Table:
        table = original(**kwargs)
        for row in table.rows:
            row["trade_time"] = row["trade_time"] + timedelta(days=1)
        return table

    repo.scan_window = _wrong_day  # type: ignore[method-assign]
    with pytest.raises(FeatureLookupError):
        build_minute_factor_values(
            repo,
            as_of=opens[-1],
            opens=opens,
            start=opens[4],
            end=opens[5],
            contract=_contract(),
            universe_at=_fixed("000001.SZ"),
            computed_at=_AS_OF_STAMP,
            run_id="test",
        )
