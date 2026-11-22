"""前瞻收益纯计算：端点、四个 horizon、节假日、停牌状态码、未成熟与除权。零存储依赖。"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.calendar import CalendarDay, open_dates
from quantagent.domain.errors import CalendarLookupError, InvalidQueryError
from quantagent.domain.forward_return import (
    build_forward_returns,
    forward_return_read_window,
    horizon_steps,
)
from quantagent.domain.prices.types import DailyPrice

if TYPE_CHECKING:
    from collections.abc import Sequence

    from quantagent.domain.forward_return import ForwardReturn

# 2024 春节休市：2 月 9 日至 16 日。其余周一至周五为开市日。
_HOLIDAYS = frozenset(date(2024, 2, d) for d in range(9, 17))
_CAL_START = date(2024, 1, 1)
_CAL_END = date(2024, 7, 31)
_AS_OF = date(2024, 7, 31)
_STATUS_TRADING = -1
_STATUS_SUSPENDED = 0
_STATUS_XD = 2
_STATUS_DR = 4


def _contract(grade: str = "A") -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": "src.wind.ashareeodprices",
            "doc_ref": "docs/contracts/src-wind-ashareeodprices.md",
            "temporal_kind": "point_event",
            "event_field": "TRADE_DT",
            "visibility": {
                "rule": "same_day_close",
                "grade": grade,
                "rationale": "单元测试用的日行情可见性规则说明足够长，满足校验要求",
            },
            "pit_recoverable": True,
        }
    )


def _calendar() -> tuple[CalendarDay, ...]:
    rows: list[CalendarDay] = []
    day = _CAL_START
    while day <= _CAL_END:
        is_open = day.weekday() < 5 and day not in _HOLIDAYS
        rows.append(CalendarDay(cal_dt=day, exchange="SSE", is_open=is_open, prev_trade_dt=None))
        day += timedelta(days=1)
    return tuple(rows)


def _opens() -> tuple[date, ...]:
    return open_dates(_calendar())


def _price(
    day: date,
    code: str,
    adj_open: Decimal | None,
    *,
    status: int | None = _STATUS_TRADING,
) -> DailyPrice:
    return DailyPrice(
        trade_dt=day,
        wind_code=code,
        open=Decimal("10"),
        high=Decimal("10"),
        low=Decimal("10"),
        close=Decimal("10"),
        volume=Decimal("1"),
        amount=Decimal("1"),
        pct_change=None,
        adj_open=adj_open,
        trade_status_code=status,
    )


def _series(
    code: str, *, base: Decimal = Decimal("100"), step: Decimal = Decimal("1")
) -> list[DailyPrice]:
    """每个开市日 adj_open 递增，便于人工核对端点。"""
    return [_price(day, code, base + step * index) for index, day in enumerate(_opens())]


def _replace_row(rows: list[DailyPrice], day: date, code: str, **changes: Any) -> list[DailyPrice]:
    out: list[DailyPrice] = []
    for row in rows:
        if row.trade_dt == day and row.wind_code == code:
            out.append(replace(row, **changes))
        else:
            out.append(row)
    return out


def _build(
    prices: list[DailyPrice],
    *,
    signal_dates: tuple[date, ...],
    horizons: tuple[str, ...] = ("1d", "5d", "10d", "20d"),
    as_of: date = _AS_OF,
    contract: VisibilityContract | None = None,
) -> tuple[ForwardReturn, ...]:
    return build_forward_returns(
        prices,
        _calendar(),
        signal_dates=signal_dates,
        contract=contract or _contract(),
        as_of=as_of,
        horizons=horizons,
    )


def _pick(rows: Sequence[ForwardReturn], *, horizon: str, event: date) -> ForwardReturn | None:
    matched = [r for r in rows if r.horizon == horizon and r.event_dt == event]
    assert len(matched) <= 1
    return matched[0] if matched else None


@pytest.mark.unit
def test_value_is_adj_open_ratio_with_open_to_open_endpoints() -> None:
    opens = _opens()
    t = date(2024, 1, 2)
    idx = opens.index(t)
    prices = _series("000001.SZ")
    rows = _build(prices, signal_dates=(t,), horizons=("1d",))
    row = _pick(rows, horizon="1d", event=t)
    assert row is not None
    # 1d：起点 T+1 开盘，终点 T+2 开盘（第 h+1 个开市日）。
    assert row.start_dt == opens[idx + 1]
    assert row.end_dt == opens[idx + 2]
    start_px = Decimal("100") + Decimal(idx + 1)
    end_px = Decimal("100") + Decimal(idx + 2)
    assert row.value == float(end_px / start_px - Decimal(1))
    assert row.return_leg == "open2open"
    assert row.return_kind == "total"
    assert row.benchmark_id == "none"


@pytest.mark.unit
@pytest.mark.parametrize("horizon", ["1d", "5d", "10d", "20d"])
def test_end_is_h_plus_one_open_day_for_each_horizon(horizon: str) -> None:
    opens = _opens()
    t = date(2024, 3, 4)
    idx = opens.index(t)
    rows = _build(_series("000001.SZ"), signal_dates=(t,), horizons=(horizon,))
    row = _pick(rows, horizon=horizon, event=t)
    assert row is not None
    steps = horizon_steps(horizon)
    assert row.end_dt == opens[idx + steps + 1]
    assert row.start_dt == opens[idx + 1]
    assert row.knowledge_dt == row.end_dt
    assert row.end_dt > row.start_dt > row.event_dt


@pytest.mark.unit
def test_start_after_weekend_and_spring_festival_uses_next_open_day() -> None:
    t = date(2024, 2, 8)  # 周四，之后是春节休市
    rows = _build(_series("000001.SZ"), signal_dates=(t,), horizons=("1d",))
    row = _pick(rows, horizon="1d", event=t)
    assert row is not None
    assert row.start_dt == date(2024, 2, 19)
    assert row.end_dt not in _HOLIDAYS
    assert row.end_dt.weekday() < 5


@pytest.mark.unit
def test_signal_day_must_be_open_day() -> None:
    with pytest.raises(CalendarLookupError, match="不是开市日"):
        _build(_series("000001.SZ"), signal_dates=(date(2024, 1, 6),), horizons=("1d",))


@pytest.mark.unit
def test_missing_start_row_produces_no_row() -> None:
    t = date(2024, 1, 2)
    opens = _opens()
    start = opens[opens.index(t) + 1]
    prices = [p for p in _series("000001.SZ") if p.trade_dt != start]
    assert _pick(_build(prices, signal_dates=(t,), horizons=("1d",)), horizon="1d", event=t) is None


@pytest.mark.unit
def test_missing_end_row_produces_no_row() -> None:
    t = date(2024, 1, 2)
    opens = _opens()
    end = opens[opens.index(t) + 2]
    prices = [p for p in _series("000001.SZ") if p.trade_dt != end]
    assert _pick(_build(prices, signal_dates=(t,), horizons=("1d",)), horizon="1d", event=t) is None


@pytest.mark.unit
@pytest.mark.parametrize("which", ["start", "end"])
def test_suspended_endpoint_status_zero_produces_no_row(which: str) -> None:
    t = date(2024, 1, 2)
    opens = _opens()
    idx = opens.index(t)
    day = opens[idx + 1] if which == "start" else opens[idx + 2]
    prices = _replace_row(
        _series("000001.SZ"), day, "000001.SZ", trade_status_code=_STATUS_SUSPENDED
    )
    assert _pick(_build(prices, signal_dates=(t,), horizons=("1d",)), horizon="1d", event=t) is None


@pytest.mark.unit
@pytest.mark.parametrize("status", [_STATUS_XD, _STATUS_DR])
def test_ex_rights_and_dividend_status_are_still_trading(status: int) -> None:
    t = date(2024, 1, 2)
    opens = _opens()
    idx = opens.index(t)
    prices = _replace_row(
        _series("000001.SZ"), opens[idx + 2], "000001.SZ", trade_status_code=status
    )
    row = _pick(_build(prices, signal_dates=(t,), horizons=("1d",)), horizon="1d", event=t)
    assert row is not None


@pytest.mark.unit
def test_unknown_status_code_fails_closed() -> None:
    t = date(2024, 1, 2)
    opens = _opens()
    prices = _replace_row(
        _series("000001.SZ"),
        opens[opens.index(t) + 1],
        "000001.SZ",
        trade_status_code=None,
    )
    assert _pick(_build(prices, signal_dates=(t,), horizons=("1d",)), horizon="1d", event=t) is None


@pytest.mark.unit
@pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-3"), None, Decimal("NaN")])
def test_non_positive_or_missing_or_non_finite_adj_open_produces_no_row(
    bad: Decimal | None,
) -> None:
    t = date(2024, 1, 2)
    opens = _opens()
    prices = _replace_row(
        _series("000001.SZ"),
        opens[opens.index(t) + 2],
        "000001.SZ",
        adj_open=bad,
    )
    assert _pick(_build(prices, signal_dates=(t,), horizons=("1d",)), horizon="1d", event=t) is None


@pytest.mark.unit
def test_immature_horizon_is_not_produced_and_as_of_inclusive_end_is() -> None:
    t = date(2024, 1, 2)
    opens = _opens()
    idx = opens.index(t)
    end = opens[idx + 6]  # 5d 的终点
    prices = _series("000001.SZ")
    before = _build(prices, signal_dates=(t,), horizons=("5d",), as_of=end - timedelta(days=1))
    assert _pick(before, horizon="5d", event=t) is None
    exact = _build(prices, signal_dates=(t,), horizons=("5d",), as_of=end)
    assert _pick(exact, horizon="5d", event=t) is not None


@pytest.mark.unit
def test_pit_grade_is_derived_from_price_contract_and_knowledge_is_end() -> None:
    t = date(2024, 1, 2)
    rows = _build(
        _series("000001.SZ"), signal_dates=(t,), horizons=("1d",), contract=_contract("B")
    )
    row = _pick(rows, horizon="1d", event=t)
    assert row is not None
    assert row.pit_grade == "B"
    assert row.knowledge_dt == row.end_dt


@pytest.mark.unit
def test_ex_dividend_inside_interval_is_neutralised_by_adj_open() -> None:
    """构造数据：除权日原始开盘价腰斩，后复权 adj_open 连续。收益应取 adj_open，不是跳空。"""
    t = date(2024, 1, 2)
    opens = _opens()
    idx = opens.index(t)
    start = opens[idx + 1]
    end = opens[idx + 2]
    prices = _series("000001.SZ", base=Decimal("10"), step=Decimal("0"))
    prices = _replace_row(prices, start, "000001.SZ", adj_open=Decimal("10"), open=Decimal("10"))
    prices = _replace_row(prices, end, "000001.SZ", adj_open=Decimal("10.5"), open=Decimal("5.2"))
    row = _pick(_build(prices, signal_dates=(t,), horizons=("1d",)), horizon="1d", event=t)
    assert row is not None
    assert row.start_dt == start
    assert row.end_dt == end
    assert row.value == pytest.approx(0.05)


@pytest.mark.unit
def test_output_is_sorted_and_deterministic() -> None:
    t = date(2024, 1, 2)
    prices = _series("600000.SH") + _series("000001.SZ")
    first = _build(prices, signal_dates=(t, t), horizons=("5d", "1d"))
    second = _build(list(reversed(prices)), signal_dates=(t,), horizons=("1d", "5d"))
    assert first == second
    keys = [(r.asset_id, r.event_dt, horizon_steps(r.horizon)) for r in first]
    assert keys == sorted(keys)


@pytest.mark.unit
def test_unknown_horizon_is_rejected() -> None:
    with pytest.raises(InvalidQueryError, match="不支持的 horizon"):
        _build(_series("000001.SZ"), signal_dates=(date(2024, 1, 2),), horizons=("60d",))


@pytest.mark.unit
def test_read_window_covers_earliest_signal_to_latest_end() -> None:
    t1 = date(2024, 1, 2)
    t2 = date(2024, 1, 5)
    window = forward_return_read_window(
        _calendar(),
        signal_dates=(t1, t2),
        horizons=("1d", "5d"),
        as_of=_AS_OF,
    )
    opens = _opens()
    assert window == (t1, opens[opens.index(t2) + 6])


@pytest.mark.unit
def test_read_window_is_none_when_nothing_matures() -> None:
    assert (
        forward_return_read_window(
            _calendar(),
            signal_dates=(date(2024, 1, 2),),
            horizons=("20d",),
            as_of=date(2024, 1, 5),
        )
        is None
    )
