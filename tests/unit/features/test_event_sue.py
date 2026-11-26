"""``event_sue`` 库函数与面板聚合的单元测试。

算法正确性的权威验证是 golden 对拍与 pandas 交叉对拍（300 随机零分歧，见提交说明）；
这里固定关键边界语义的回归：单季化、Q1 特殊值、同比差分、双统计窗口、去重 keep-last、
不足 13 行放弃、std=0/NaN 不产值，以及面板的月份/时效过滤、多源先到先得、同键 AVG。
"""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal

import pytest

from quantagent.domain.fundamental.types import (
    EarningsEventRecord,
    ProfitSeriesRecord,
)
from quantagent.features.library.fundamental.event_sue import (
    FEATURE_ID,
    event_sue,
)
from quantagent.features.panel.event_sue import (
    _dedup_events,
    _period_end_date,
    build_event_sue_values,
)


def _profit_row(year: int, quarter: int, np_yuan: float, rtype: int = 1001) -> ProfitSeriesRecord:
    return ProfitSeriesRecord(
        asset_id="000001.SZ",
        report_year=year,
        report_quarter=quarter,
        report_type=rtype,
        declare_dt=date(2020, 1, 1),
        np_shareholder=Decimal(str(np_yuan)),
    )


# 固定波动序列（万元累计净利）：每季增量有真实起伏，q_diff_4 方差非零，能产值。
# 线性递增序列会让 q_diff_4 恒定、std=0 不产值，不能用作测试数据。
_CUM_WAN = {
    (2019, 1001): 111.6666, (2019, 1002): 230.8506, (2019, 1003): 375.5454, (2019, 1004): 488.1409,
    (2020, 1001): 115.5489, (2020, 1002): 236.6658, (2020, 1003): 329.5921, (2020, 1004): 445.4257,
    (2021, 1001): 124.0918, (2021, 1002): 259.6002, (2021, 1003): 346.1888, (2021, 1004): 447.4269,
    (2022, 1001): 86.3469, (2022, 1002): 223.0221, (2022, 1003): 351.5627, (2022, 1004): 434.4944,
    (2023, 1001): 95.1, (2023, 1002): 240.5, (2023, 1003): 362.8, (2023, 1004): 451.2,
}


def _full_history() -> list[ProfitSeriesRecord]:
    """2019-2022 每年四季度完整累计净利（元），有真实波动（std 非零）能产值。"""
    return [
        _profit_row(year, quarter, cum_wan * 10000.0)
        for (year, quarter), cum_wan in sorted(_CUM_WAN.items())
    ]


@pytest.mark.unit
def test_sue_returns_value_for_complete_history() -> None:
    value = event_sue(report_year=2023, report_quarter=1001, profit=150.0, history=_full_history())
    assert value is not None
    assert math.isfinite(value)


@pytest.mark.unit
def test_sue_abandons_when_history_below_13_rows() -> None:
    # 12 行 < 13：旧代码 len(profit_data) < 13 直接 return。
    value = event_sue(
        report_year=2023, report_quarter=1001, profit=150.0, history=_full_history()[:12]
    )
    assert value is None


@pytest.mark.unit
def test_sue_none_when_std_zero_constant_profit() -> None:
    # 每季单季净利恒定 → q_diff_4 全 0 → std=0 → 除零不产值。
    rows: list[ProfitSeriesRecord] = []
    for year in (2019, 2020, 2021, 2022):
        cum = [100.0, 200.0, 300.0, 400.0]
        for qi, quarter in enumerate((1001, 1002, 1003, 1004)):
            rows.append(_profit_row(year, quarter, cum[qi] * 10000.0))
    value = event_sue(report_year=2023, report_quarter=1001, profit=110.0, history=rows)
    assert value is None


@pytest.mark.unit
def test_sue_none_when_period_ly_missing() -> None:
    # 缺 2022Q1（去年同期）→ period_ly 不在序列 → None。
    rows = [r for r in _full_history() if not (r.report_year == 2022 and r.report_quarter == 1001)]
    # 去掉后序列仍 >= 13 行才检验 period_ly 缺失分支
    assert len(rows) >= 13
    value = event_sue(report_year=2023, report_quarter=1001, profit=150.0, history=rows)
    assert value is None


@pytest.mark.unit
def test_q1_uses_cumulative_directly() -> None:
    # Q1 特殊化含在算法内（单季=累计）：完整序列能产值即验证该路径不报错。
    value = event_sue(report_year=2023, report_quarter=1001, profit=150.0, history=_full_history())
    assert value is not None


@pytest.mark.unit
def test_keep_last_prefers_adjusted_1003() -> None:
    # 同 period 的 1001 与 1003 调整版并存，keep-last 保留 1003（排序后 1003 在后）。
    rows: list[ProfitSeriesRecord] = []
    for (year, quarter), cum_wan in sorted(_CUM_WAN.items()):
        rows.append(_profit_row(year, quarter, cum_wan * 10000.0, rtype=1001))
        # 同 period 加一条 1003 调整版，值不同（扰动累计）
        rows.append(_profit_row(year, quarter, (cum_wan + 7.0) * 10000.0, rtype=1003))
    value_with = event_sue(report_year=2023, report_quarter=1001, profit=150.0, history=rows)
    rows_1001_only = [r for r in rows if r.report_type == 1001]
    value_without = event_sue(
        report_year=2023, report_quarter=1001, profit=150.0, history=rows_1001_only
    )
    # 两者应不同（证明 1003 调整版参与了，即 keep-last 生效）
    assert value_with is not None and value_without is not None
    assert value_with != value_without


# ---- 面板层：事件过滤、去重、AVG ----


def _event(
    asset: str,
    declare: date,
    year: int,
    quarter: int,
    profit: float,
    *,
    source: str = "income",
) -> EarningsEventRecord:
    return EarningsEventRecord(
        asset_id=asset,
        declare_dt=declare,
        report_year=year,
        report_quarter=quarter,
        profit=Decimal(str(profit)),
        source=source,
    )


@pytest.mark.unit
def test_period_end_date_mapping() -> None:
    assert _period_end_date(2023, 1001) == date(2023, 3, 31)
    assert _period_end_date(2023, 1002) == date(2023, 6, 30)
    assert _period_end_date(2023, 1003) == date(2023, 9, 30)
    assert _period_end_date(2023, 1004) == date(2023, 12, 31)


@pytest.mark.unit
def test_dedup_filters_correction_months() -> None:
    # 月份 ∉ {1,2,3,4,7,8,10} 剔除（5/6/9/11/12 月）。
    may = _event("000001.SZ", date(2024, 5, 15), 2024, 1001, 100.0)
    apr = _event("000001.SZ", date(2024, 4, 15), 2024, 1001, 100.0)
    kept = _dedup_events([may, apr])
    declares = [e.declare_dt for e in kept]
    assert date(2024, 5, 15) not in declares
    assert date(2024, 4, 15) in declares


@pytest.mark.unit
def test_dedup_filters_late_disclosure() -> None:
    # 公告日距报告期末 > 4*31 天剔除。2023Q4 期末 2023-12-31，公告 2024-06-15 远超 → 剔除。
    # 但 6 月本身也不在有效月份，改用 4 月底的晚期：2023Q1 期末 2023-03-31，公告 2024-04-30 超 4*31 天。
    late = _event("000001.SZ", date(2024, 4, 30), 2023, 1001, 100.0)
    assert _dedup_events([late]) == []


@pytest.mark.unit
def test_dedup_first_wins_multisource() -> None:
    # 同键 (declare, asset, period) 三源共存，forecast 优先（首位）。
    d = date(2024, 4, 30)
    fc = _event("000001.SZ", d, 2024, 1001, 100.0, source="forecast")
    inc = _event("000001.SZ", d, 2024, 1001, 200.0, source="income")
    # adapter 已按 forecast→income→express 排序，这里模拟该顺序
    kept = _dedup_events([fc, inc])
    assert len(kept) == 1
    assert kept[0].profit == Decimal("100.0")  # forecast 的 profit 保留


@pytest.mark.unit
def test_same_day_multi_period_averaged() -> None:
    # 同股同公告日两个报告期（年报+一季报）→ 两个事件各自算 sue → AVG 一行。
    # 公告日 2024-04-30：2023Q4 期末 2023-12-31 与 2024Q1 期末 2024-03-31 都在 4*31 天内。
    # 两事件历史序列需覆盖到各自 period 之前，故历史含 2023 全年。
    d = date(2024, 4, 30)
    e_q4 = _event("000001.SZ", d, 2023, 1004, 451.2)  # 2023 年报
    e_q1 = _event("000001.SZ", d, 2024, 1001, 130.0)  # 2024 一季报
    history = _full_history()
    domain = {d: frozenset({"000001.SZ"})}
    built = build_event_sue_values(
        events=[e_q4, e_q1],
        profit_rows=history,
        domain_by_day=domain,
        computed_at=datetime(2024, 12, 31),
        run_id="t",
    )
    # 同键两行应聚合成一行
    same_key = [v for v in built.values if v.event_dt == d and v.asset_id == "000001.SZ"]
    assert len(same_key) == 1
    assert same_key[0].feature_id == FEATURE_ID


@pytest.mark.unit
def test_event_not_in_domain_dropped() -> None:
    d = date(2024, 4, 16)
    e = _event("000001.SZ", d, 2024, 1001, 150.0)
    # 域内不含该股
    domain = {d: frozenset({"600000.SZ"})}
    built = build_event_sue_values(
        events=[e],
        profit_rows=_full_history(),
        domain_by_day=domain,
        computed_at=datetime(2024, 12, 31),
        run_id="t",
    )
    assert built.values == ()


@pytest.mark.unit
def test_nontrading_declare_uses_next_trading_day_domain() -> None:
    # 核心回归（裁定 B1）：非交易日（周六）declare 的事件不落丢，域判定用 declare 后首个交易日。
    # wx2 19.3% 事件行来自非交易日 declare。2024-04-27 周六（披露期 4 月），declare 后首个交易日 4-29 周一。
    sat = date(2024, 4, 27)  # 周六 declare
    mon = date(2024, 4, 29)  # 周一，declare 后首个交易日
    e = _event("000001.SZ", sat, 2024, 1001, 150.0)
    # domain_by_day 只有交易日键：周六无域，周一有域含该股。
    domain = {mon: frozenset({"000001.SZ"})}
    built = build_event_sue_values(
        events=[e],
        profit_rows=_full_history(),
        domain_by_day=domain,
        computed_at=datetime(2024, 12, 31),
        run_id="t",
    )
    # event_dt 仍为 declare（周六），但事件因股票在周一域内而产值。
    assert len(built.values) == 1
    assert built.values[0].event_dt == sat


@pytest.mark.unit
def test_nontrading_declare_dropped_when_stock_not_in_next_day_domain() -> None:
    # 非交易日 declare，但股票在 declare 后首个交易日域外（ST/非 all_a）→ 不落行。
    sat = date(2024, 4, 27)
    mon = date(2024, 4, 29)
    e = _event("000001.SZ", sat, 2024, 1001, 150.0)
    domain = {mon: frozenset({"600000.SH"})}  # 周一域内不含该股
    built = build_event_sue_values(
        events=[e],
        profit_rows=_full_history(),
        domain_by_day=domain,
        computed_at=datetime(2024, 12, 31),
        run_id="t",
    )
    assert built.values == ()


@pytest.mark.unit
def test_candidate_count_distinguishes_legit_empty() -> None:
    # 合法空/异常空区分依据 candidate_count：非披露期事件被月份过滤光 → candidate_count=0；
    # 披露期有候选但股票不在域/缺历史 → candidate_count>0 但 values 可为空（materialize 据此报错）。
    may = _event("000001.SZ", date(2024, 5, 15), 2024, 1001, 100.0)  # 5 月被月份过滤
    apr = _event("000001.SZ", date(2024, 4, 15), 2024, 1001, 150.0)  # 4 月有效候选
    domain_empty: dict = {}
    # 5 月事件：过滤后候选 0
    built_may = build_event_sue_values(
        events=[may],
        profit_rows=_full_history(),
        domain_by_day=domain_empty,
        computed_at=datetime(2024, 12, 31),
        run_id="t",
    )
    assert built_may.candidate_count == 0
    assert built_may.values == ()
    # 4 月事件：候选 1，但域空导致未产值
    built_apr = build_event_sue_values(
        events=[apr],
        profit_rows=_full_history(),
        domain_by_day=domain_empty,
        computed_at=datetime(2024, 12, 31),
        run_id="t",
    )
    assert built_apr.candidate_count == 1
    assert built_apr.values == ()  # 域空 → 异常空场景（candidate_count>0 却零产出）
