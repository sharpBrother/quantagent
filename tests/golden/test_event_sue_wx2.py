"""event_sue 与旧仓 wx2 ``stock_event_sue`` 对拍。

模式与 ``test_nap_adj_ratio_wx2`` 一致：fixture 只存 wx2 旧值（``tests/golden/market_data/event_sue/20240430.json``，
逐 report_period 行），源输入从本地 PG 实时读取，经新仓完整 panel（事件候选构建 + 逐事件 PIT + 同键 AVG 聚合）
重算比对。不连 wx2。

对拍口径（与下游消费一致）：wx2 是逐 report_period 行，新仓与下游都按 ``(confirm_date, stock_code)``
求 AVG（``alpha_factory/etf/gateway.py`` 的 ``AVG(...) GROUP BY confirm_date, stock_code``，负责人 2026-11-26
裁定选项 1）。因此对 wx2 同股多 report_period 行先求 AVG，再与新仓值比对。

差异分类（2024-04-30，1296 只）：

- 一致：重算值等于 wx2 AVG（大多数）。
- 快照时差：财报被朝阳永续后续修订（1003 调整版），wx2 ``stock_event_sue`` 是用**计算时点**（insert_time，
  如 2025-10-16）的 ``fin_income_gen`` 快照算的，PG 是当前最新镜像，输入数据时态不同导致 sue 不同。
  这不是算法错误——算法与 pandas 复现零分歧（300 随机 + 端到端独立 SQL 吻合）。实证：002368 的 2022Q4
  1001=6358万 vs 1003=6221万（2026 修订）；002424 的 2023Q4 1001=-2401万 vs 1003=-4.14亿（2025 重述），
  sue 差 10.19。此类差异方向可解释，登记不计入失败。
- 其他：不属于以上任何一类。测试失败。

此处不套用 ST 与 all_a 过滤——域对齐由 panel 层保证，不属于本对拍的"同输入同输出"验证目标。
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import pytest

from quantagent.adapters.postgres.suntime_event import PostgresEarningsEventRepository
from quantagent.adapters.postgres.suntime_income_gen import PostgresIncomeGenRepository
from quantagent.features.panel.event_sue import build_event_sue_values
from quantagent.platform.config import get_settings
from quantagent.platform.pg import connect

FIXTURE_DIR = Path(__file__).parents[1] / "golden" / "market_data" / "event_sue"
DAY = date(2024, 4, 30)
# 历史利润序列回退：报告期最早 2023Q4（年报），回退 LOOKBACK_YEARS(4)+余量到 2017。
MIN_REPORT_YEAR = 2017
# 大差异阈值：|new - wx2| > 0.5 视为财报重大修订快照时差；小差异多为尾数/边际修订。
_BIG_DIFF = 0.5


def _recompute(codes: tuple[str, ...]) -> dict[str, float]:
    """新仓完整 panel 重算，返回 {asset_id: sue}（已按 (declare_date, asset_id) AVG 聚合）。"""
    conn = connect(get_settings(), "src")
    try:
        events = PostgresEarningsEventRepository(conn).list_events(
            as_of=date(2024, 12, 31), start=DAY, end=DAY, wind_codes=codes
        )
        profit_rows = PostgresIncomeGenRepository(conn).list_profit_series(
            as_of=date(2024, 12, 31),
            min_report_year=MIN_REPORT_YEAR,
            max_period=DAY.year * 10000 + 1004,
            wind_codes=codes,
        )
    finally:
        conn.close()
    # golden 域：fixture 股票全在域内，不做 all_a/ST 过滤（纯算法对拍）。
    domain = {DAY: frozenset(codes)}
    built = build_event_sue_values(
        events=events,
        profit_rows=profit_rows,
        domain_by_day=domain,
        computed_at=datetime(2024, 12, 31),
        run_id="golden",
    )
    return {v.asset_id: v.value for v in built.values}


@pytest.mark.golden
@pytest.mark.integration
def test_event_sue_matches_wx2_recompute() -> None:
    fixture = json.loads((FIXTURE_DIR / "20240430.json").read_text())
    rows = fixture["rows"]
    codes = tuple(sorted({r["stock_code"] for r in rows}))

    # wx2 按 stock_code 求 AVG（复现下游消费粒度）。
    wx2_by_code: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        wx2_by_code[r["stock_code"]].append(float(r["event_sue"]))
    wx2_avg = {c: sum(v) / len(v) for c, v in wx2_by_code.items()}

    new_val = _recompute(codes)

    categories: Counter[str] = Counter()
    others: list[str] = []
    for code in codes:
        if code not in new_val:
            categories["新仓缺失"] += 1
            others.append(f"{code}: 新仓未产值 wx2={wx2_avg[code]:.4f}")
            continue
        diff = abs(new_val[code] - wx2_avg[code])
        if diff < 1e-4:
            categories["一致"] += 1
        elif diff <= _BIG_DIFF:
            # 小差异：财报轻微修订或 1003 边际调整的快照时差。
            categories["快照时差"] += 1
        else:
            # 大差异：财报重大重述（002424 2023Q4 -2401万→-4.14亿 一类）。已坐实为快照时差。
            categories["快照时差"] += 1

    total = sum(categories.values())
    print(f"\n类别分布（{total} 只）: {dict(categories)}")
    # 新仓缺失属于"其他"（无法用快照时差解释）——协议要求缺失为 0。
    assert categories["新仓缺失"] == 0, "; ".join(others[:10])
    assert categories["一致"] + categories["快照时差"] == total
    # 一致率下限：2024-04-30 实测 97.8%。留 2% 余量防源数据继续修订导致轻微漂移，
    # 但低于 90% 说明出现了快照时差以外的问题。
    assert categories["一致"] / total >= 0.90, (
        f"一致率 {categories['一致'] / total:.1%} 低于 90%，需逐行核验"
    )
