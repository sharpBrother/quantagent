"""与旧仓 wx2 ``dbo.macro_us_treasury_yield`` 对拍：宽转长后的 (trade_date, maturity, yield) 必须一致。
fixture 是 2024-11-01 至 2025-01-31 的只读抽样（793 行，61 个交易日，13 个期限）：
- ``*_long.csv``：wx2 原表行，列为 trade_date、maturity、yield、source。
- ``*_wide.csv``：由同一批 wx2 行透视成 ``pro.us_tycr`` 的宽表形状（列为 date 与接口期限列），缺期限留空。
源端 ``source`` 是旧值 ``tushare:us_tycr``，新仓写 ``tushare.us_tycr``，所以对拍不比较 source。
"""

from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from quantagent.ingest.sources.tushare.us_treasury_yield import us_treasury_wide_to_long

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LONG = FIXTURES / "us_treasury_yield_wx2_202411_202501_long.csv"
WIDE = FIXTURES / "us_treasury_yield_wx2_202411_202501_wide.csv"

_START = "20241101"
_END = "20250131"


def _wx2_long() -> dict[tuple[str, str], Decimal]:
    with LONG.open(encoding="utf-8", newline="") as handle:
        return {
            (row["trade_date"], row["maturity"]): Decimal(row["yield"])
            for row in csv.DictReader(handle)
        }


@pytest.mark.golden
def test_wide_to_long_matches_wx2_macro_us_treasury_yield_rows() -> None:
    # 按 pro.us_tycr 的真实形状读：日期为字符串，收益率为浮点数。
    wide = pd.read_csv(WIDE, dtype={"date": str})
    rows = us_treasury_wide_to_long(
        wide,
        start_date=_START,
        end_date=_END,
        ingested_at=datetime(2026, 1, 2, 11, 0),
    )
    produced = {(str(r["trade_date"]), str(r["maturity"])): r["yield"] for r in rows}
    expected = _wx2_long()
    assert len(produced) == len(rows) == len(expected) == 793
    assert produced.keys() == expected.keys()
    mismatched = [key for key in expected if produced[key] != expected[key]]
    assert mismatched == []


@pytest.mark.golden
def test_fixtures_stay_under_repo_file_limit() -> None:
    # AGENTS.md §10：单文件体积上限 512KB。
    for path in (LONG, WIDE):
        assert path.stat().st_size < 512 * 1024, path.name
