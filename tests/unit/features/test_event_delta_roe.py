"""``event_delta_roe`` 库函数与面板聚合的单元测试。

算法正确性的权威验证是 golden 对拍（重算 vs wx2 stock_event_delta_roe）；这里固定关键边界语义：
Wind ROE 优先 vs profit 重算二分支、roe_last 缺失硬条件、Q1/非Q1 单季化、股东权益上一期、
last_period 映射、域判定（非交易日 declare 用首个交易日）、同键 AVG、candidate_count 区分。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from quantagent.domain.fundamental.types import (
    EarningsEventRecord,
    ProfitSeriesRecord,
    RoeRecord,
    ShareholderEquityRecord,
)
from quantagent.features.library.fundamental.event_delta_roe import (
    event_delta_roe,
    last_period,
    recomputed_roe,
)
from quantagent.features.panel.event_delta_roe import (
    _dedup_events,
    build_event_delta_roe_values,
)


def _event(asset: str, declare: date, year: int, quarter: int, profit: float) -> EarningsEventRecord:
    return EarningsEventRecord(
        asset_id=asset,
        declare_dt=declare,
        report_year=year,
        report_quarter=quarter,
        profit=Decimal(str(profit)),
        source="income",
    )


def _roe(asset: str, period: date, ann: date, roe: float | None) -> RoeRecord:
    return RoeRecord(
        asset_id=asset,
        report_period=period,
        ann_dt=ann,
        s_qfa_roe=None if roe is None else Decimal(str(roe)),
    )


def _equity(asset: str, period: date, eqt_yuan: float) -> ShareholderEquityRecord:
    return ShareholderEquityRecord(
        asset_id=asset,
        report_period=period,
        ann_dt=date(2024, 4, 30),
        shrhldr_eqt=Decimal(str(eqt_yuan)),
    )


def _profit_row(asset: str, year: int, quarter: int, np_yuan: float, rtype: int = 1001) -> ProfitSeriesRecord:
    return ProfitSeriesRecord(
        asset_id=asset,
        report_year=year,
        report_quarter=quarter,
        report_type=rtype,
        declare_dt=date(2024, 4, 30),
        np_shareholder=Decimal(str(np_yuan)),
    )


# ---------- 纯函数 ----------


@pytest.mark.unit
def test_event_delta_roe_is_difference() -> None:
    assert event_delta_roe(roe_current=2.5, roe_last=2.0) == pytest.approx(0.5)
    assert event_delta_roe(roe_current=None, roe_last=2.0) is None
    assert event_delta_roe(roe_current=2.5, roe_last=None) is None


@pytest.mark.unit
def test_recomputed_roe() -> None:
    # 100*profit_q/eqt，同单位（万）。
    assert recomputed_roe(profit_q=100.0, equity_wan=1000.0) == pytest.approx(10.0)
    assert recomputed_roe(profit_q=100.0, equity_wan=0.0) is None  # 除零
    assert recomputed_roe(profit_q=None, equity_wan=1000.0) is None


@pytest.mark.unit
def test_last_period_mapping() -> None:
    # 0331(1001)→前年1231(1004)；0630→0331；0930→0630；1231→0930。
    assert last_period(2024, 1001) == (2023, 1004)
    assert last_period(2024, 1002) == (2024, 1001)
    assert last_period(2024, 1003) == (2024, 1002)
    assert last_period(2024, 1004) == (2024, 1003)


# ---------- panel：Wind 优先分支 ----------


@pytest.mark.unit
def test_wind_roe_preferred_when_available() -> None:
    # 600000 风格：当期与去年同期都有 Wind ROE → delta=当期-去年同期，不用重算。
    declare = date(2024, 4, 30)
    ev = _event("600000.SH", declare, 2024, 1001, 150.0)  # 2024Q1
    roe_rows = [
        _roe("600000.SH", date(2023, 3, 31), date(2023, 4, 29), 2.242767),  # period_ly
        _roe("600000.SH", date(2024, 3, 31), date(2024, 4, 30), 2.373834),  # period
    ]
    built = build_event_delta_roe_values(
        events=[ev],
        roe_rows=roe_rows,
        equity_rows=[],
        profit_rows=[],
        domain_by_day={declare: frozenset({"600000.SH"})},
        computed_at=datetime(2024, 12, 31),
        run_id="t",
    )
    assert len(built.values) == 1
    # delta = 2.373834 - 2.242767 = 0.131067
    assert built.values[0].value == pytest.approx(0.131067, abs=1e-4)
    assert built.values[0].event_dt == declare


@pytest.mark.unit
def test_no_value_when_period_ly_missing() -> None:
    # period_ly 不在 ROE 序列 → 整个事件不产值（硬条件），即便当期有 Wind ROE。
    declare = date(2024, 4, 30)
    ev = _event("600000.SH", declare, 2024, 1001, 150.0)
    roe_rows = [_roe("600000.SH", date(2024, 3, 31), date(2024, 4, 30), 2.37)]  # 只有当期无去年同期
    built = build_event_delta_roe_values(
        events=[ev],
        roe_rows=roe_rows,
        equity_rows=[],
        profit_rows=[],
        domain_by_day={declare: frozenset({"600000.SH"})},
        computed_at=datetime(2024, 12, 31),
        run_id="t",
    )
    assert built.values == ()
    assert built.candidate_count == 1  # 候选在，是异常空场景


# ---------- panel：profit 重算分支 ----------


@pytest.mark.unit
def test_recompute_branch_q1() -> None:
    # 当期 Wind ROE 缺失 → 重算。Q1 profit_q=profit 直接用累计。eqt 用上一期(2023Q4)。
    declare = date(2024, 4, 30)
    ev = _event("000001.SZ", declare, 2024, 1001, 100.0)  # 2024Q1 profit=100万
    roe_rows = [
        _roe("000001.SZ", date(2023, 3, 31), date(2023, 4, 29), 2.0),  # period_ly roe_last=2.0
        # 当期 period 无 Wind ROE（触发重算）
    ]
    # eqt 上一期 2023Q4 = 1000万（1e7元）
    equity_rows = [_equity("000001.SZ", date(2023, 12, 31), 1e7)]
    built = build_event_delta_roe_values(
        events=[ev],
        roe_rows=roe_rows,
        equity_rows=equity_rows,
        profit_rows=[],
        domain_by_day={declare: frozenset({"000001.SZ"})},
        computed_at=datetime(2024, 12, 31),
        run_id="t",
    )
    assert len(built.values) == 1
    # 重算 roe = 100*100/10000(eq万) ... 注意 eqt 1e7元/10000=1000万, profit=100万
    # roe = 100*100/1000 = 10.0; delta = 10.0 - 2.0 = 8.0
    assert built.values[0].value == pytest.approx(8.0)


@pytest.mark.unit
def test_recompute_branch_non_q1_subtracts_last_period() -> None:
    # 非 Q1（如 Q2）：profit_q = profit - get_profit(last_period)。
    declare = date(2024, 8, 30)
    ev = _event("000001.SZ", declare, 2024, 1002, 250.0)  # 2024Q2 累计profit=250万
    roe_rows = [_roe("000001.SZ", date(2023, 6, 30), date(2023, 8, 30), 3.0)]  # period_ly=2023Q2
    equity_rows = [_equity("000001.SZ", date(2024, 3, 31), 1e7)]  # last_period=2024Q1, eqt 1000万
    # get_profit(2024Q1) 累计=100万
    profit_rows = [_profit_row("000001.SZ", 2024, 1001, 100.0 * 10000)]
    built = build_event_delta_roe_values(
        events=[ev],
        roe_rows=roe_rows,
        equity_rows=equity_rows,
        profit_rows=profit_rows,
        domain_by_day={declare: frozenset({"000001.SZ"})},
        computed_at=datetime(2024, 12, 31),
        run_id="t",
    )
    assert len(built.values) == 1
    # profit_q = 250 - 100 = 150万; roe = 100*150/1000 = 15.0; delta = 15.0 - 3.0 = 12.0
    assert built.values[0].value == pytest.approx(12.0)


@pytest.mark.unit
def test_no_value_when_equity_missing_in_recompute() -> None:
    # 重算分支缺股东权益 → 不产值。
    declare = date(2024, 4, 30)
    ev = _event("000001.SZ", declare, 2024, 1001, 100.0)
    roe_rows = [_roe("000001.SZ", date(2023, 3, 31), date(2023, 4, 29), 2.0)]
    built = build_event_delta_roe_values(
        events=[ev],
        roe_rows=roe_rows,
        equity_rows=[],  # 无股东权益
        profit_rows=[],
        domain_by_day={declare: frozenset({"000001.SZ"})},
        computed_at=datetime(2024, 12, 31),
        run_id="t",
    )
    assert built.values == ()


# ---------- panel：域判定 / AVG / candidate_count ----------


@pytest.mark.unit
def test_nontrading_declare_uses_next_trading_day_domain() -> None:
    # 非交易日（周六）declare → 域判定用 declare 后首个交易日（裁定 B1）。event_dt 仍为 declare。
    sat = date(2024, 4, 27)  # 周六
    mon = date(2024, 4, 29)  # 周一
    ev = _event("600000.SH", sat, 2024, 1001, 150.0)
    roe_rows = [
        _roe("600000.SH", date(2023, 3, 31), date(2023, 4, 29), 2.24),
        _roe("600000.SH", date(2024, 3, 31), date(2024, 4, 27), 2.37),
    ]
    built = build_event_delta_roe_values(
        events=[ev],
        roe_rows=roe_rows,
        equity_rows=[],
        profit_rows=[],
        domain_by_day={mon: frozenset({"600000.SH"})},  # 周一域含该股，周六无域
        computed_at=datetime(2024, 12, 31),
        run_id="t",
    )
    assert len(built.values) == 1
    assert built.values[0].event_dt == sat  # event_dt=declare(周六)


@pytest.mark.unit
def test_avg_aggregates_same_declare_multi_period() -> None:
    # 同股同 declare 两报告期（年报+一季报）→ 两值 AVG。
    declare = date(2024, 4, 30)
    e_q4 = _event("600000.SH", declare, 2023, 1004, 400.0)  # 2023年报
    e_q1 = _event("600000.SH", declare, 2024, 1001, 150.0)  # 2024Q1
    roe_rows = [
        _roe("600000.SH", date(2022, 12, 31), date(2023, 4, 30), 5.0),  # q4 period_ly=2022年报
        _roe("600000.SH", date(2023, 12, 31), date(2024, 4, 30), 4.0),  # q4 period
        _roe("600000.SH", date(2023, 3, 31), date(2023, 4, 29), 2.0),  # q1 period_ly=2023Q1
        _roe("600000.SH", date(2024, 3, 31), date(2024, 4, 30), 2.5),  # q1 period
    ]
    built = build_event_delta_roe_values(
        events=[e_q4, e_q1],
        roe_rows=roe_rows,
        equity_rows=[],
        profit_rows=[],
        domain_by_day={declare: frozenset({"600000.SH"})},
        computed_at=datetime(2024, 12, 31),
        run_id="t",
    )
    # q4 delta = 4.0-5.0 = -1.0; q1 delta = 2.5-2.0 = 0.5; AVG = (-1.0+0.5)/2 = -0.25
    assert len(built.values) == 1
    assert built.values[0].value == pytest.approx(-0.25)


@pytest.mark.unit
def test_dedup_month_filter_and_first_wins() -> None:
    # 与 event_sue 同源：5 月非披露期过滤；同键 forecast 优先于 income。
    may = _event("000001.SZ", date(2024, 5, 15), 2024, 1001, 100.0)
    apr_first = _event("000001.SZ", date(2024, 4, 15), 2024, 1001, 100.0)
    apr_second = _event("000001.SZ", date(2024, 4, 15), 2024, 1001, 200.0)
    kept = _dedup_events([apr_first, apr_second, may])
    assert len(kept) == 1
    assert kept[0].profit == Decimal("100.0")  # 同键先到先得，保留首行


@pytest.mark.unit
def test_candidate_count_legit_empty() -> None:
    may = _event("000001.SZ", date(2024, 5, 15), 2024, 1001, 100.0)  # 5月过滤
    built = build_event_delta_roe_values(
        events=[may],
        roe_rows=[],
        equity_rows=[],
        profit_rows=[],
        domain_by_day={},
        computed_at=datetime(2024, 12, 31),
        run_id="t",
    )
    assert built.candidate_count == 0
    assert built.values == ()
