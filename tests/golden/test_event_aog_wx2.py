"""event_aog 与旧仓 wx2 ``stock_event_aog`` 对拍。

模式与 ``test_event_sue_wx2`` 一致：fixture 只存 wx2 旧值（``tests/golden/market_data/event_aog/20240429.json``，
逐 report_period 行），源输入从本地 PG 实时读取，经新仓完整 panel（事件候选构建 + 开盘日判定 +
夜盘涨幅重算 + 同键 AVG）重算比对。不连 wx2。

对拍口径：aog 的 ``event_dt = open_date = confirm_date``（下游 ``alpha_factory/etf/gateway.py`` 注释：
``event_*`` 的 effective date 是 confirm_date）。故按 ``confirm_date = 20240429`` 对齐——wx2 同股多
report_period 行先求 AVG（复现下游 ``AVG(...) GROUP BY confirm_date, stock_code`` 消费粒度），新仓取
``event_dt = 20240429`` 的行，逐一比对。

为什么选 2024-04-29（周一）：年报+一季报披露高峰，且覆盖**非交易日 declare**关键场景——
wx2 confirm=20240429 的 2302 行来自三个 declare 日：20240427 周六（1627 行，70%，周末披露高峰）、
20240429 周一当日（667 行）、20240426 周五（8 行，9:25 后入库次日反映）。域判定在 open_date
（裁定 A1）使周六 declare 正确落到周一 open_date，是覆盖正确性的核心验证。

结果（2026-11-26 实测）：1569 只股票 **100% 一致**（match=1569 diff=0 missing=0）。event_aog 纯
行情计算、不依赖历史财报序列，无 event_sue 的财报修订快照时差，故可达成零差异。此处不套用
ST 与 all_a 过滤——域对齐由 panel 层保证，不属于本对拍的"同输入同输出"验证目标。
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import pytest

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.daily_prices import PostgresDailyPriceRepository
from quantagent.adapters.postgres.index_returns import PostgresIndexReturnRepository
from quantagent.adapters.postgres.suntime_event import PostgresEarningsEventRepository
from quantagent.domain.calendar import open_dates
from quantagent.features.library.fundamental.event_aog import BENCHMARK_INDEX
from quantagent.features.panel.event_aog import build_event_aog_values
from quantagent.platform.config import get_settings
from quantagent.platform.pg import connect
from quantagent.platform.storage.paths import detect_repo_root, resolve_var_paths

FIXTURE_DIR = Path(__file__).parents[1] / "golden" / "market_data" / "event_aog"
# confirm_date（= open_date）对齐日。declare 窗口覆盖贡献该 confirm 的三个 declare 日。
CONFIRM_DAY = date(2024, 4, 29)
DECLARE_START = date(2024, 4, 26)  # 周五（9:25 后入库次日反映到周一）
DECLARE_END = date(2024, 4, 29)  # 周一当日
# 行情/日历窗口向后宽限（open_date 可能落在 declare 后数个交易日）。
PX_END = date(2024, 5, 10)


def _recompute(codes: tuple[str, ...]) -> dict[str, float]:
    """新仓完整 panel 重算，返回 {asset_id: aog}（仅 event_dt=CONFIRM_DAY，已同键 AVG）。"""
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    conn = connect(settings, "src")
    as_of = date(2024, 12, 31)
    try:
        events = PostgresEarningsEventRepository(conn).list_events(
            as_of=as_of, start=DECLARE_START, end=DECLARE_END, wind_codes=codes
        )
        stock_prices = PostgresDailyPriceRepository(conn).list_prices(
            as_of=as_of, start=DECLARE_START, end=PX_END, wind_codes=codes
        )
        index_returns = PostgresIndexReturnRepository(conn).list_returns(
            as_of=as_of, start=DECLARE_START, end=PX_END, wind_codes=(BENCHMARK_INDEX,)
        )
    finally:
        conn.close()
    days = LakeCalendarRepository(paths.lake / "std" / "trade_calendar").list_days(
        as_of=as_of, exchange="SSE", start=DECLARE_START, end=PX_END
    )
    opens = open_dates(days)
    # golden 域：fixture 股票在所有交易日全在域，不做 all_a/ST 过滤（纯算法对拍）。
    domain = {day: frozenset(codes) for day in opens}
    built = build_event_aog_values(
        events=events,
        stock_prices=stock_prices,
        index_returns=index_returns,
        open_day_set=frozenset(opens),
        domain_by_day=domain,
        computed_at=datetime(2024, 12, 31),
        run_id="golden",
    )
    return {v.asset_id: v.value for v in built.values if v.event_dt == CONFIRM_DAY}


@pytest.mark.golden
@pytest.mark.integration
def test_event_aog_matches_wx2_recompute() -> None:
    fixture = json.loads((FIXTURE_DIR / "20240429.json").read_text())
    rows = fixture["rows"]
    codes = tuple(sorted({r["stock_code"] for r in rows}))

    # wx2 按 stock_code 求 AVG（复现下游消费粒度）。
    wx2_by_code: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        wx2_by_code[r["stock_code"]].append(float(r["event_aog"]))
    wx2_avg = {c: sum(v) / len(v) for c, v in wx2_by_code.items()}

    new_val = _recompute(codes)

    categories: Counter[str] = Counter()
    missing: list[str] = []
    diffs: list[str] = []
    for code in codes:
        if code not in new_val:
            categories["新仓缺失"] += 1
            missing.append(code)
            continue
        if abs(new_val[code] - wx2_avg[code]) < 1e-4:
            categories["一致"] += 1
        else:
            categories["不一致"] += 1
            diffs.append(f"{code}: 新{new_val[code]:.4f} wx2{wx2_avg[code]:.4f}")

    total = sum(categories.values())
    print(f"\n类别分布（{total} 只）: {dict(categories)}")
    # event_aog 纯行情计算，无快照时差，应达成零缺失零不一致。留极小余量防源端行情微调，
    # 但 2026-11-26 实测 100% 一致。任何不一致/缺失都需逐行核验，不设宽限类别。
    assert categories["新仓缺失"] == 0, f"缺失: {missing[:10]}"
    assert categories["不一致"] == 0, f"不一致: {diffs[:10]}"
    assert categories["一致"] == total
