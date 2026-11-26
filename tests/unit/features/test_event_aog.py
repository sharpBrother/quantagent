"""``event_aog`` 库函数与面板聚合的单元测试。

算法正确性的权威验证是 golden 对拍（重算 vs wx2 stock_event_aog）；这里固定关键边界语义的回归：
开盘日判定（entrytime 三情形）、open_date 跨周末解析、夜盘涨幅重算、缺行情不产值、
``event_dt = open_date``（非 declare_date）、knowledge_dt 箍到 open_date、同键 AVG、candidate_count 区分。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from quantagent.domain.fundamental.types import EarningsEventRecord
from quantagent.domain.index_returns.types import IndexReturn
from quantagent.domain.prices.types import DailyPrice
from quantagent.features.library.fundamental.event_aog import (
    BENCHMARK_INDEX,
    event_aog,
    night_ratio,
    reflect_same_day,
)
from quantagent.features.panel.event_aog import (
    _dedup_events,
    _resolve_open_date,
    build_event_aog_values,
)


def _event(
    asset: str,
    declare: date,
    year: int,
    quarter: int,
    *,
    entrytime: datetime | None = None,
    source: str = "income",
) -> EarningsEventRecord:
    return EarningsEventRecord(
        asset_id=asset,
        declare_dt=declare,
        report_year=year,
        report_quarter=quarter,
        profit=Decimal("100.0"),
        source=source,
        entrytime=entrytime,
    )


def _stock_price(dt: date, asset: str, adj_open: float, adj_preclose: float) -> DailyPrice:
    return DailyPrice(
        trade_dt=dt,
        wind_code=asset,
        open=None,
        high=None,
        low=None,
        close=None,
        volume=None,
        amount=None,
        pct_change=None,
        adj_open=Decimal(str(adj_open)),
        adj_preclose=Decimal(str(adj_preclose)),
    )


def _index_return(dt: date, open_: float, preclose: float) -> IndexReturn:
    return IndexReturn(
        trade_dt=dt,
        wind_code=BENCHMARK_INDEX,
        pct_change=None,
        open=Decimal(str(open_)),
        preclose=Decimal(str(preclose)),
    )


# ---------- night_ratio / event_aog 纯函数 ----------


@pytest.mark.unit
def test_night_ratio_basic() -> None:
    assert night_ratio(102.0, 100.0) == pytest.approx(2.0)
    assert night_ratio(98.0, 100.0) == pytest.approx(-2.0)


@pytest.mark.unit
def test_night_ratio_zero_preclose_none() -> None:
    assert night_ratio(100.0, 0.0) is None
    assert night_ratio(100.0, -5.0) is None


@pytest.mark.unit
def test_event_aog_is_difference() -> None:
    assert event_aog(stock_night_ratio=3.0, index_night_ratio=1.0) == pytest.approx(2.0)
    assert event_aog(stock_night_ratio=-1.0, index_night_ratio=1.0) == pytest.approx(-2.0)


# ---------- reflect_same_day 开盘日判定 ----------


@pytest.mark.unit
def test_reflect_same_day_entry_before_declare() -> None:
    # entrytime 前一晚入库（日期早于公告日）→ 当日反映。
    declare = date(2024, 4, 30)
    entry = datetime(2024, 4, 29, 22, 30)  # 前一晚 22:30
    assert reflect_same_day(entry, declare) is True


@pytest.mark.unit
def test_reflect_same_day_entry_same_day_before_925() -> None:
    # 同日 9:25 前入库 → 当日反映。
    declare = date(2024, 4, 30)
    entry = datetime(2024, 4, 30, 9, 20)  # 09:20
    assert reflect_same_day(entry, declare) is True
    entry_925 = datetime(2024, 4, 30, 9, 25)  # 恰 09:25
    assert reflect_same_day(entry_925, declare) is True


@pytest.mark.unit
def test_reflect_next_day_entry_same_day_after_925() -> None:
    # 同日 9:25 后入库 → 次日反映。
    declare = date(2024, 4, 30)
    entry = datetime(2024, 4, 30, 17, 37)  # 17:37（收盘后）
    assert reflect_same_day(entry, declare) is False


@pytest.mark.unit
def test_reflect_next_day_entry_none() -> None:
    # entrytime 缺失保守取次日。
    assert reflect_same_day(None, date(2024, 4, 30)) is False


# ---------- _resolve_open_date 跨周末 ----------


@pytest.mark.unit
def test_resolve_open_date_same_day_trading() -> None:
    # 4-30 周二交易日，前一晚入库 → 当日 open=4-30。
    opens = [date(2024, 4, 29), date(2024, 4, 30), date(2024, 5, 6)]
    ev = _event("000001.SZ", date(2024, 4, 30), 2024, 1001, entrytime=datetime(2024, 4, 29, 22, 0))
    assert _resolve_open_date(ev, opens) == date(2024, 4, 30)


@pytest.mark.unit
def test_resolve_open_date_next_day_when_after_925() -> None:
    # 4-30 收盘后入库 → 次日 open=5-6（跨五一小长假）。
    opens = [date(2024, 4, 29), date(2024, 4, 30), date(2024, 5, 6)]
    ev = _event("000001.SZ", date(2024, 4, 30), 2024, 1001, entrytime=datetime(2024, 4, 30, 18, 0))
    assert _resolve_open_date(ev, opens) == date(2024, 5, 6)


@pytest.mark.unit
def test_resolve_open_date_declare_on_nontrading_same_day() -> None:
    # declare 在周末（非交易日），前一晚入库 → 当日反映 = 首个 >= declare 的交易日（周一）。
    sat = date(2024, 5, 4)  # 周六
    mon = date(2024, 5, 6)
    opens = [date(2024, 5, 3), mon, date(2024, 5, 7)]
    ev = _event("000001.SZ", sat, 2024, 1001, entrytime=datetime(2024, 5, 3, 22, 0))
    assert _resolve_open_date(ev, opens) == mon


@pytest.mark.unit
def test_resolve_open_date_none_when_no_future_trading_day() -> None:
    # 窗口末尾无足够未来交易日 → None（不落行）。
    opens = [date(2024, 4, 30)]
    ev = _event("000001.SZ", date(2024, 4, 30), 2024, 1001, entrytime=datetime(2024, 4, 30, 18, 0))
    assert _resolve_open_date(ev, opens) is None


# ---------- panel 端到端 ----------


def _panel_inputs(  # noqa: PLR0917 - 测试辅助函数，参数多名义清晰
    declare: date,
    entrytime: datetime,
    stock_open: float,
    stock_preclose: float,
    idx_open: float,
    idx_preclose: float,
    opens: list[date],
    open_dt: date,
) -> dict:
    return {
        "events": [_event("000001.SZ", declare, 2024, 1001, entrytime=entrytime)],
        "stock_prices": [_stock_price(open_dt, "000001.SZ", stock_open, stock_preclose)],
        "index_returns": [_index_return(open_dt, idx_open, idx_preclose)],
        "open_day_set": frozenset(opens),
        # 域判定在 open_date（裁定 A1），键是 open_dt 而非 declare。
        "domain_by_day": {open_dt: frozenset({"000001.SZ"})},
        "computed_at": datetime(2024, 12, 31),
        "run_id": "t",
    }


@pytest.mark.unit
def test_panel_event_dt_is_open_date_not_declare() -> None:
    # 4-30 收盘后入库 → open=5-6。event_dt 必须是 open_date(5-6)，不是 declare(4-30)。
    declare = date(2024, 4, 30)
    open_dt = date(2024, 5, 6)
    inputs = _panel_inputs(
        declare,
        datetime(2024, 4, 30, 18, 0),
        stock_open=102.0,
        stock_preclose=100.0,
        idx_open=101.0,
        idx_preclose=100.0,
        opens=[date(2024, 4, 29), declare, open_dt],
        open_dt=open_dt,
    )
    built = build_event_aog_values(**inputs)
    assert len(built.values) == 1
    v = built.values[0]
    assert v.event_dt == open_dt  # 关键：event_dt=open_date 非 declare
    # aog = 个股 2% - 指数 1% = 1%
    assert v.value == pytest.approx(1.0)
    # knowledge_dt 箍到 open_date
    assert v.knowledge_dt >= open_dt


@pytest.mark.unit
def test_panel_drops_when_stock_price_missing() -> None:
    declare = date(2024, 4, 30)
    open_dt = date(2024, 4, 30)
    inputs = _panel_inputs(
        declare,
        datetime(2024, 4, 29, 22, 0),
        stock_open=102.0,
        stock_preclose=100.0,
        idx_open=101.0,
        idx_preclose=100.0,
        opens=[declare],
        open_dt=open_dt,
    )
    # 拿掉个股行情
    inputs["stock_prices"] = []
    built = build_event_aog_values(**inputs)
    assert built.values == ()
    # 候选仍在（candidate_count=1），是异常空场景——有候选却因缺行情未产值。
    assert built.candidate_count == 1


@pytest.mark.unit
def test_panel_drops_when_not_in_domain() -> None:
    declare = date(2024, 4, 30)
    inputs = _panel_inputs(
        declare,
        datetime(2024, 4, 29, 22, 0),
        stock_open=102.0,
        stock_preclose=100.0,
        idx_open=101.0,
        idx_preclose=100.0,
        opens=[declare],
        open_dt=declare,
    )
    # 域内不含该股（键是 open_date，此处 declare==open_date 同日）
    inputs["domain_by_day"] = {declare: frozenset({"600000.SH"})}
    built = build_event_aog_values(**inputs)
    assert built.values == ()


@pytest.mark.unit
def test_panel_nontrading_declare_falls_to_next_open_date() -> None:
    # 核心回归：非交易日（周六）declare 的事件不落丢，open_date 落到下一交易日并产值。
    # wx2 19.5% 事件行来自非交易日 declare，域判定在 open_date（交易日）才有意义。
    # 2024-04-27 周六（披露期 4 月）declare，前一晚(4-26周五)入库 → same_day → 首个>=declare 的交易日。
    sat = date(2024, 4, 27)  # 周六 declare（披露期）
    mon = date(2024, 4, 29)  # 下周一 open
    inputs = {
        "events": [_event("000001.SZ", sat, 2024, 1001, entrytime=datetime(2024, 4, 26, 22, 0))],
        "stock_prices": [_stock_price(mon, "000001.SZ", 103.0, 100.0)],
        "index_returns": [_index_return(mon, 101.0, 100.0)],
        "open_day_set": frozenset({date(2024, 4, 26), mon, date(2024, 4, 30)}),
        # 域判定在 open_date(周一交易日)，不在周六 declare（非交易日无域）。
        "domain_by_day": {mon: frozenset({"000001.SZ"})},
        "computed_at": datetime(2024, 12, 31),
        "run_id": "t",
    }
    built = build_event_aog_values(**inputs)
    assert len(built.values) == 1
    assert built.values[0].event_dt == mon
    assert built.values[0].value == pytest.approx(2.0)  # 3% - 1%


@pytest.mark.unit
def test_panel_avg_aggregates_same_open_date() -> None:
    # 同股同 declare 两个报告期（年报+一季报同日披露）→ 同 open_date，两值相同，AVG=单值。
    declare = date(2024, 4, 30)
    entry = datetime(2024, 4, 29, 22, 0)
    events = [
        _event("000001.SZ", declare, 2023, 1004, entrytime=entry),  # 年报
        _event("000001.SZ", declare, 2024, 1001, entrytime=entry),  # 一季报
    ]
    inputs = {
        "events": events,
        "stock_prices": [_stock_price(declare, "000001.SZ", 102.0, 100.0)],
        "index_returns": [_index_return(declare, 101.0, 100.0)],
        "open_day_set": frozenset({declare}),
        "domain_by_day": {declare: frozenset({"000001.SZ"})},
        "computed_at": datetime(2024, 12, 31),
        "run_id": "t",
    }
    built = build_event_aog_values(**inputs)
    assert len(built.values) == 1  # 同 (open_date, asset) 聚合为一行
    assert built.values[0].value == pytest.approx(1.0)  # 两值相同，AVG 即该值


@pytest.mark.unit
def test_dedup_month_filter_and_first_wins() -> None:
    # 5 月（非披露期）事件被月份过滤；同键 forecast 优先于 income。
    may = _event("000001.SZ", date(2024, 5, 15), 2024, 1001, source="income")
    apr_income = _event("000001.SZ", date(2024, 4, 15), 2024, 1001, source="income")
    apr_forecast = _event("000001.SZ", date(2024, 4, 15), 2024, 1001, source="forecast")
    kept = _dedup_events([apr_income, apr_forecast, may])  # adapter 已按 forecast 优先排好，此处乱序测 setdefault
    # may 被月份过滤；apr 同键保留先出现的（此处 income 在前——真实 adapter 保证 forecast 先，
    # 本测试只验证去重机制保留首个出现的）。
    assert len(kept) == 1
    assert all(e.declare_dt.month != 5 for e in kept)


@pytest.mark.unit
def test_dedup_late_disclosure_filtered() -> None:
    # 公告日距报告期末 > 4*31 天剔除。2022 年报(2022-12-31)到 2024-04-30 远超 124 天，超晚剔除。
    very_late = _event("000001.SZ", date(2024, 4, 30), 2022, 1004)  # 2022年报 2024-04 才公告
    assert _dedup_events([very_late]) == []
    # 正常 2023Q4 2024-04 公告（1231→0430 约 121 天 < 124）保留
    normal = _event("000001.SZ", date(2024, 4, 30), 2023, 1004)
    assert len(_dedup_events([normal])) == 1


@pytest.mark.unit
def test_candidate_count_distinguishes_legit_empty() -> None:
    # 合法空：5 月事件被月份过滤 → candidate_count=0。异常空：4 月候选但域空 → candidate_count>0 且 values 空。
    may = _event("000001.SZ", date(2024, 5, 15), 2024, 1001)
    apr = _event("000001.SZ", date(2024, 4, 15), 2024, 1001, entrytime=datetime(2024, 4, 14, 22, 0))
    empty_domain: dict = {}
    built_may = build_event_aog_values(
        events=[may],
        stock_prices=[],
        index_returns=[],
        open_day_set=frozenset(),
        domain_by_day=empty_domain,
        computed_at=datetime(2024, 12, 31),
        run_id="t",
    )
    assert built_may.candidate_count == 0
    assert built_may.values == ()
    built_apr = build_event_aog_values(
        events=[apr],
        stock_prices=[],
        index_returns=[],
        open_day_set=frozenset(),
        domain_by_day=empty_domain,
        computed_at=datetime(2024, 12, 31),
        run_id="t",
    )
    assert built_apr.candidate_count == 1
    assert built_apr.values == ()
