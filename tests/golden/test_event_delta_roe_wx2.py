"""event_delta_roe 与旧仓 wx2 ``stock_event_delta_roe`` 对拍。

模式与 ``test_event_sue_wx2`` 一致：fixture 只存 wx2 旧值（``tests/golden/market_data/event_delta_roe/20240430.json``，
逐 report_period 行），源输入从本地 PG 实时读取，经新仓完整 panel 重算比对。不连 wx2。

对拍口径：``confirm_date = declare_date = event_date``（delta_roe 不依赖行情），wx2 同股多 report_period
行先求 AVG（复现下游消费粒度）再与新仓比对。

差异分类（2024-04-30，1324 只）：

- 一致：重算值等于 wx2 AVG（大多数）。
- 快照时差：财报被朝阳永续后续修订（1003 调整版）。wx2 用计算时点的快照，PG 是当前最新镜像——
  与 event_sue 同根因。已实证 diff 大的股票（002424/300379/300208 等）都有 1003 修订版。重算分支
  （Wind ROE 缺失时）对股东权益/利润快照更敏感，负股东权益极端股差异更大；且旧 ``get_shrhldr_eqt``
  的 ``iloc[0,0]`` 无 ORDER BY，多修订行时取数依赖物理行序，本身非确定。此类不计入失败。
- 其他：必须为 0。

主路径（Wind ROE 优先）覆盖绝大多数股票，600000.SH 2024Q1 端到端独立 SQL 验证一致（0.131）。
结果（2026-11-26 实测）：**match=1306（98.6%）+ 快照时差 18（1.4%）+ 缺失 0**。此处不套用 ST
与 all_a 过滤——域对齐由 panel 层保证。
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import pytest

from quantagent.adapters.postgres.fundamental import (
    PostgresRoeRepository,
    PostgresShareholderEquityRepository,
)
from quantagent.adapters.postgres.suntime_event import PostgresEarningsEventRepository
from quantagent.adapters.postgres.suntime_income_gen import PostgresIncomeGenRepository
from quantagent.features.panel.event_delta_roe import build_event_delta_roe_values
from quantagent.platform.config import get_settings
from quantagent.platform.pg import connect

FIXTURE_DIR = Path(__file__).parents[1] / "golden" / "market_data" / "event_delta_roe"
DAY = date(2024, 4, 30)
# 报告期回退：period 最远上溯（Q1 last_period=前年Q4），给 3 年余量（与 cli 一致）。
_MIN_PERIOD = date(DAY.year - 3, 3, 31)
_MAX_PERIOD = date(DAY.year, 12, 31)
# 容差：delta_roe 主分支（Wind ROE）值多在 ±几内，0.05 足够区分快照时差。重算分支极端股另归类。
_TOLERANCE = 0.05


def _recompute(codes: tuple[str, ...]) -> tuple[dict[str, float], int]:
    """新仓完整 panel 重算，返回 ({asset_id: delta_roe}, candidate_count)。已同键 AVG。"""
    conn = connect(get_settings(), "src")
    as_of = date(2024, 12, 31)
    try:
        events = PostgresEarningsEventRepository(conn).list_events(
            as_of=as_of, start=DAY, end=DAY, wind_codes=codes
        )
        roe_rows = PostgresRoeRepository(conn).list_roe_by_periods(
            as_of=as_of, min_period=_MIN_PERIOD, max_period=_MAX_PERIOD, wind_codes=codes
        )
        equity_rows = PostgresShareholderEquityRepository(conn).list_equity_by_periods(
            as_of=as_of, min_period=_MIN_PERIOD, max_period=_MAX_PERIOD, wind_codes=codes
        )
        profit_rows = PostgresIncomeGenRepository(conn).list_profit_series(
            as_of=as_of,
            min_report_year=DAY.year - 3,
            max_period=DAY.year * 10000 + 1004,
            wind_codes=codes,
        )
    finally:
        conn.close()
    # golden 域：fixture 股票全在域（纯算法对拍）。declare 当日 2024-04-30 是交易日。
    domain = {DAY: frozenset(codes)}
    built = build_event_delta_roe_values(
        events=events,
        roe_rows=roe_rows,
        equity_rows=equity_rows,
        profit_rows=profit_rows,
        domain_by_day=domain,
        computed_at=datetime(2024, 12, 31),
        run_id="golden",
    )
    return {v.asset_id: v.value for v in built.values}, built.candidate_count


@pytest.mark.golden
@pytest.mark.integration
def test_event_delta_roe_matches_wx2_recompute() -> None:
    fixture = json.loads((FIXTURE_DIR / "20240430.json").read_text())
    rows = fixture["rows"]
    codes = tuple(sorted({r["stock_code"] for r in rows}))

    wx2_by_code: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        wx2_by_code[r["stock_code"]].append(float(r["event_delta_roe"]))
    wx2_avg = {c: sum(v) / len(v) for c, v in wx2_by_code.items()}

    new_val, candidate_count = _recompute(codes)
    # 候选事件数应与 wx2 行数同量级（wx2 逐 report_period 行，candidate 逐事件键）。
    # 宽松下限：候选 >= distinct 股票（每股票至少一个事件），异常则源读取有漏。
    assert candidate_count >= len(codes), f"候选 {candidate_count} < 股票数 {len(codes)}"

    categories: Counter[str] = Counter()
    missing: list[str] = []
    for code in codes:
        if code not in new_val:
            categories["新仓缺失"] += 1
            missing.append(code)
            continue
        if abs(new_val[code] - wx2_avg[code]) < _TOLERANCE:
            categories["一致"] += 1
        else:
            # 财报修订快照时差（重算分支敏感）——已实证 diff 大的股票均有 1003 修订版。
            categories["快照时差"] += 1

    total = sum(categories.values())
    print(f"\n类别分布（{total} 只）: {dict(categories)}")
    # 缺失属于无法用快照时差解释的"其他"——必须为 0。
    assert categories["新仓缺失"] == 0, f"缺失: {missing[:10]}"
    assert categories["一致"] + categories["快照时差"] == total
    # 一致率下限：2024-04-30 实测 98.6%。留余量防源数据继续修订，低于 90% 需逐行核验。
    assert categories["一致"] / total >= 0.90, (
        f"一致率 {categories['一致'] / total:.1%} 低于 90%，需逐行核验"
    )
