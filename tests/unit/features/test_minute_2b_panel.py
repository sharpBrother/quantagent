"""第二批分钟因子面板的接线：窗口、排除日、血缘与截面残差。使用内存假仓储，不碰 PG 与 lake。"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from quantagent.contracts.loader import load_bundle
from quantagent.domain.errors import FeatureLookupError
from quantagent.domain.prices.types import DailyPrice
from quantagent.features.panel.minute_2b import build_minute_2b_values

if TYPE_CHECKING:
    from collections.abc import Sequence

_MINUTE = "src.minprice.ashare_minute_bar"
_PRICE = "src.wind.ashareeodprices"
_AS_OF = date(2026, 11, 23)
_COMPUTED = datetime(2026, 11, 24, tzinfo=UTC).replace(tzinfo=None)
_CORE_UP = "pf_single_core_up_20_mean_pos_neut_pxret21"
_CORE_DOWN = "pf_single_core_down_20_mean_neg_neut_pxret21"
_CORR = "pf_single_corr_vrlaglarge_5_mean_neg"


@dataclass(frozen=True)
class _Table:
    rows: list[dict[str, Any]]

    @property
    def num_rows(self) -> int:
        return len(self.rows)

    def to_pylist(self) -> list[dict[str, Any]]:
        return self.rows


class _FakeMinute:
    def __init__(
        self, data: dict[date, dict[str, list[tuple[float, float]]]], excluded: dict[date, set[str]]
    ) -> None:
        self._data = data
        self._excluded = excluded

    def excluded_codes(self, *, as_of: date, day: date) -> frozenset[str]:
        return frozenset(self._excluded.get(day, set()))

    def scan_window(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        codes: Sequence[str] | None = None,
        columns: Sequence[str] | None = None,
    ) -> _Table:
        rows: list[dict[str, Any]] = []
        day = start
        day_map = self._data.get(day, {})
        for code, bars in day_map.items():
            if codes is not None and code not in codes:
                continue
            for i, (close, vol) in enumerate(bars):
                rows.append(
                    {
                        "ts_code": code,
                        "trade_time": datetime.combine(day, time(9, 30)) + timedelta(minutes=i),
                        "close": close,
                        "vol": vol,
                    }
                )
        return _Table(rows)


class _FakePrices:
    def __init__(self, prices: dict[tuple[str, date], float]) -> None:
        self._prices = prices

    def list_prices(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        wind_codes: tuple[str, ...],
    ) -> tuple[DailyPrice, ...]:
        out = []
        for (code, day), value in self._prices.items():
            if start <= day <= end and code in wind_codes:
                out.append(
                    DailyPrice(
                        trade_dt=day,
                        wind_code=code,
                        open=None,
                        high=None,
                        low=None,
                        close=None,
                        volume=None,
                        amount=None,
                        pct_change=None,
                        adj_close=Decimal(str(value)),
                    )
                )
        return tuple(out)


def _world(seed: int, n_days: int, codes: list[str]) -> tuple[list[date], _FakeMinute, _FakePrices]:
    rng = random.Random(seed)
    opens = [date(2026, 1, 1) + timedelta(days=i) for i in range(n_days)]
    data: dict[date, dict[str, list[tuple[float, float]]]] = {}
    prices: dict[tuple[str, date], float] = {}
    for code in codes:
        base = 10.0 + rng.random()
        level = base
        for day in opens:
            bars = []
            price = level
            for _ in range(8):
                price = max(0.01, round(price * (1 + rng.choice([-0.01, 0.0, 0.01])), 2))
                bars.append((price, float(rng.randint(1, 4))))
            data.setdefault(day, {})[code] = bars
            level = price
            prices[(code, day)] = level * 5
    return opens, _FakeMinute(data, {opens[18]: {codes[0]}}), _FakePrices(prices)


def _run(
    opens: list[date],
    minute: _FakeMinute,
    prices: _FakePrices,
    *,
    start: date,
    end: date,
    ids: tuple[str, ...],
    codes: list[str],
) -> tuple[Any, ...]:
    bundle = load_bundle()
    return build_minute_2b_values(
        minute,
        prices,
        as_of=_AS_OF,
        opens=opens,
        start=start,
        end=end,
        minute_contract=bundle.visibilities[_MINUTE],
        price_contract=bundle.visibilities[_PRICE],
        universe_at=lambda _day: codes,
        computed_at=_COMPUTED,
        run_id="unit-2b",
        feature_ids=ids,
    )


@pytest.mark.unit
def test_core_residuals_sum_to_zero_and_lineage_is_event_day() -> None:
    codes = [f"{i:06d}.SZ" for i in range(40)]
    opens, minute, prices = _world(5, 26, codes)
    target = opens[25]
    rows = _run(
        opens, minute, prices, start=target, end=target, ids=(_CORE_UP, _CORE_DOWN), codes=codes
    )
    assert rows
    for feature_id in (_CORE_UP, _CORE_DOWN):
        mine = [r for r in rows if r.feature_id == feature_id]
        assert mine
        # 截面 OLS 带截距：残差之和为 0。
        assert sum(r.value for r in mine) == pytest.approx(0.0, abs=1e-9)
        assert {r.knowledge_dt for r in mine} == {target}
        assert {r.pit_grade for r in mine} == {"A"}
        assert {r.definition_version for r in mine} == {"v1"}


@pytest.mark.unit
def test_corr_value_is_negated_five_day_mean_and_covers_only_scope() -> None:
    codes = [f"{i:06d}.SZ" for i in range(40)]
    opens, minute, prices = _world(8, 26, codes)
    target = opens[25]
    rows = _run(opens, minute, prices, start=target, end=target, ids=(_CORR,), codes=codes[:30])
    assert rows
    assert {r.asset_id for r in rows} <= set(codes[:30])
    assert all(r.event_dt == target for r in rows)


@pytest.mark.unit
def test_too_few_residual_observations_fail_closed() -> None:
    codes = [f"{i:06d}.SZ" for i in range(12)]
    opens, minute, prices = _world(2, 26, codes)
    target = opens[25]
    with pytest.raises(FeatureLookupError, match="少于 20"):
        _run(opens, minute, prices, start=target, end=target, ids=(_CORE_UP,), codes=codes)


@pytest.mark.unit
def test_start_needs_twenty_opens_of_history() -> None:
    codes = [f"{i:06d}.SZ" for i in range(40)]
    opens, minute, prices = _world(4, 26, codes)
    with pytest.raises(FeatureLookupError, match="不足 20"):
        _run(opens, minute, prices, start=opens[10], end=opens[11], ids=(_CORR,), codes=codes)


class _RecordingMinute(_FakeMinute):
    def __init__(self, inner: _FakeMinute) -> None:
        super().__init__(inner._data, inner._excluded)
        self.days: list[date] = []

    def scan_window(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        codes: Sequence[str] | None = None,
        columns: Sequence[str] | None = None,
    ) -> _Table:
        self.days.append(start)
        return super().scan_window(as_of=as_of, start=start, end=end, codes=codes, columns=columns)


@pytest.mark.unit
def test_corr_only_reads_five_minute_days_back() -> None:
    # 只算 corr 时不得回看 20 日分钟：源端分钟数据起点之前的日子没有分区，多读会 fail-closed 报错。
    codes = [f"{i:06d}.SZ" for i in range(30)]
    opens, minute, prices = _world(9, 26, codes)
    recording = _RecordingMinute(minute)
    target = opens[25]
    _run(opens, recording, prices, start=target, end=target, ids=(_CORR,), codes=codes)
    assert min(recording.days) == opens[21]
    recording_core = _RecordingMinute(minute)
    _run(opens, recording_core, prices, start=target, end=target, ids=(_CORE_UP,), codes=codes)
    assert min(recording_core.days) == opens[6]
