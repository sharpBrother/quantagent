"""GPR 日频与旧仓 wx2 ``dbo.macro_gpr_daily`` 对拍（2024 全年，GPRD_ACT）。

两份 fixture 的来源：
- ``gpr_daily_recent_2024_slice.dta``：从 ``data_gpr_daily_recent.dta`` 取 2024 年的行，原列保留，
  由 pandas 重新编码为 Stata 118。它不是源文件原字节，所以本测试不校验 file_sha256。
- ``gpr_daily_wx2_2024_latest.csv``：只读查询 ``dbo.macro_gpr_daily``，条件
  ``source = 'iacoviello:gpr_daily_recent'`` 且 2024 年；每个 observation_date 取 ``ingested_at`` 最新的一条。
  wx2 中 2024 年每个日期只有一个版本，所以“最新”与“唯一”结果相同。

对拍口径：wx2 的 gprd_act 是 float32 加宽到 float64 后量化到 8 位小数，与解析器的口径一致。
差异必须有解释，不允许放宽为近似比较。
"""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from quantagent.ingest.sources.macro.gpr import parse_gpr_daily_dta

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DTA = FIXTURES / "gpr_daily_recent_2024_slice.dta"
WX2 = FIXTURES / "gpr_daily_wx2_2024_latest.csv"


def _wx2_gprd_act() -> dict[str, Decimal]:
    with WX2.open(encoding="utf-8", newline="") as handle:
        return {row["observation_date"]: Decimal(row["gprd_act"]) for row in csv.DictReader(handle)}


@pytest.mark.golden
def test_gprd_act_2024_matches_wx2_on_every_date() -> None:
    parsed = parse_gpr_daily_dta(DTA.read_bytes())
    produced = {
        point.observation_date.strftime("%Y%m%d"): point.value
        for point in parsed.points
        if point.series_id == "GPRD_ACT" and point.observation_date.year == 2024
    }
    expected = _wx2_gprd_act()

    assert produced.keys() == expected.keys()
    assert len(expected) == 366
    mismatched = [
        (day, expected[day], produced[day])
        for day in sorted(expected)
        if produced[day] != expected[day]
    ]
    assert mismatched == []


@pytest.mark.golden
def test_fixture_dates_span_the_full_year() -> None:
    parsed = parse_gpr_daily_dta(DTA.read_bytes())
    assert parsed.observation_min == date(2024, 1, 1)
    assert parsed.observation_max == date(2024, 12, 31)


@pytest.mark.golden
def test_fixtures_stay_under_repo_file_limit() -> None:
    # AGENTS.md §10：单文件体积上限 512KB。
    for path in (DTA, WX2):
        assert path.stat().st_size < 512 * 1024, path.name
