"""nap_adj_ratio 与旧仓 wx2 ``stock_nap_adj_ratio.nap_adj_ratio`` 对拍。

数据来源：本地 PG ``src_suntime.rpt_earnings_adjust``（源输入，只读）+ fixture 旧值横截面
``tests/golden/market_data/nap_adj_ratio/20240515.json``（``old`` 键为带后缀代码，值为十进制字符串）。

模式与 ``test_did_ratio_wx2_live`` 一致：fixture 只存旧值横截面（小），源输入从本地 PG 实时读取
重算比对——本地 PG 与 wx2 在该窗口的源行数已验证一致（38780 行），故无需把源行存入 fixture。

口径差异（对齐新仓的既定裁定，见 ADR）：

- 旧仓逐**自然日**、覆盖全部研报股票、按 ``current_create_date`` 无 entrytime 截止（有前视）。
- 新仓逐**交易日**、all_a 减 ST、``entrytime ≤ 观察日`` 截止（消除前视）。

因此对拍不是直拍旧值，而是：用本地 PG 源输入经新仓 ``nap_adj_ratio`` 算法重算，比对旧值。
逐只股票归入以下一类，其他必须为 0：

- 一致：重算值等于旧值。entrytime 截止未剔除影响结果的行（大多数研报及时入库）。
- 消除前视：entrytime 截止剔除了影响结果的源行，重算值与旧值不同。这是裁定的刻意偏离，
  差异方向可解释（旧值用了观察日不可见的研报）。登记计数，不算不一致。
- 双方皆无值：旧值缺失且重算也不产值。
- 其他：不属于以上任何一类。测试失败，不加例外。

20240515 是交易日。此处不套用 ST 与 all_a 过滤——过滤只减少覆盖，不影响"同输入同输出"
的验证目标；域对齐已由 panel 层保证，不属于本对拍的验证范围。
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from quantagent.domain.fundamental.types import EarningsAdjustRecord
from quantagent.features.library.fundamental.nap_adj_ratio import (
    WINDOW_DAYS,
    adjust_window_rows,
    nap_adj_ratio,
)
from quantagent.platform.config import get_settings
from quantagent.platform.pg import connect

FIXTURE_DIR = Path(__file__).parents[1] / "golden" / "market_data" / "nap_adj_ratio"
DAY = date(2024, 5, 15)


def _wind_suffix(bare: str) -> str:
    head = bare[0]
    if head in "65":
        return f"{bare}.SH"
    if head == "9":
        return f"{bare}.BJ"
    return f"{bare}.SZ"


def _load_source_rows() -> dict[str, list[EarningsAdjustRecord]]:
    """从本地 PG 读窗口内全部源行，按裸码分组。窗口多取一天缓冲（entrytime >= create_dt）。"""
    lower = DAY - timedelta(days=WINDOW_DAYS)
    settings = get_settings()
    conn = connect(settings, "src")
    try:
        cur = conn.cursor()
        cur.execute(
            """
            select stock_code, current_create_date, entrytime, report_year, np_adjust_rate
            from src_suntime.rpt_earnings_adjust
            where current_create_date between %s and %s
            """,
            (lower.isoformat(), DAY.isoformat()),
        )
        grouped: dict[str, list[EarningsAdjustRecord]] = {}
        for stock_code, create_dt, entrytime, report_year, rate in cur.fetchall():
            if create_dt is None or entrytime is None:
                continue
            entry_dt = entrytime.date() if hasattr(entrytime, "date") else entrytime
            grouped.setdefault(stock_code, []).append(
                EarningsAdjustRecord(
                    asset_id=_wind_suffix(stock_code),
                    create_dt=create_dt,
                    entry_dt=entry_dt,
                    report_year=report_year,
                    np_adjust_rate=Decimal(str(rate)) if rate is not None else None,
                )
            )
        return grouped
    finally:
        conn.close()


def _classify(
    rows: list[EarningsAdjustRecord], old: Decimal | None
) -> tuple[str, Decimal | None]:
    new = nap_adj_ratio(as_of=DAY, rows=rows)
    lower = DAY - timedelta(days=WINDOW_DAYS)
    in_window = [r for r in rows if lower <= r.create_dt <= DAY]
    visible = adjust_window_rows(as_of=DAY, rows=rows)
    excluded = len(in_window) - len(visible)

    same = (new is None and old is None) or (
        new is not None and old is not None and abs(float(new) - float(old)) < 1e-9
    )
    if same:
        return ("双方皆无值" if new is None else "一致"), new
    if excluded > 0:
        return "消除前视", new
    return "其他", new


@pytest.mark.golden
@pytest.mark.integration
def test_nap_adj_ratio_matches_wx2_recompute() -> None:
    main = json.loads((FIXTURE_DIR / "20240515.json").read_text())
    old_map: dict[str, str | None] = main["old"]
    source = _load_source_rows()

    categories: Counter[str] = Counter()
    mismatches: list[str] = []
    for bare, rows in source.items():
        wind_code = _wind_suffix(bare)
        old_raw = old_map.get(wind_code)
        old = Decimal(old_raw) if old_raw is not None else None
        category, new = _classify(rows, old)
        categories[category] += 1
        if category == "其他":
            mismatches.append(
                f"{wind_code}: old={old_raw} new={None if new is None else float(new)}"
            )

    total = sum(categories.values())
    print(f"\n类别分布（{total} 只）: {dict(categories)}")
    assert categories["其他"] == 0, (
        f"{categories['其他']} 只无法用 entrytime 前视解释: " + "; ".join(mismatches[:10])
    )
    assert categories["一致"] + categories["消除前视"] + categories["双方皆无值"] == total
