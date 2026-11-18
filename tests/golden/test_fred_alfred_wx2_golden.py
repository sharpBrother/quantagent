"""FRED／ALFRED 当前版本与旧仓 wx2 ``dbo.macro_fred_observation`` 对拍（CPIAUCSL，2020-01 至 2025-12）。

fixture 来源：
- ``fred_wx2_cpiaucsl_202001_202512.csv``：wx2 只读 SELECT 的原行，``observation_date`` 为 ``char(8)``。
- ``fred_alfred_cpiaucsl_current_202001_202512.json``：ALFRED 全量拉取中 ``realtime_end = 9999-12-31``
  的当前版本，保留 FRED 原始字段，经过真实的 ``fetch_observation_vintages`` 解析。

FRED 会修订历史值，wx2 是旧仓某个时刻的快照。两边不一致时要逐条解释，不放宽断言。
目前 DFII10 与 T10YIE 没有对拍 fixture：它们超过 FRED 单次请求的 vintage date 上限，整段拉取方案待定。
"""

from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from quantagent.ingest.sources.macro.fred import FredHttpResponse, fetch_observation_vintages

if TYPE_CHECKING:
    from collections.abc import Mapping

FIXTURES = Path(__file__).resolve().parent / "fixtures"
WX2 = FIXTURES / "fred_wx2_cpiaucsl_202001_202512.csv"
ALFRED = FIXTURES / "fred_alfred_cpiaucsl_current_202001_202512.json"


class _ReplayHttp:
    """回放 fixture，不联网。fixture 只含 realtime_end=9999-12-31 的当前版本，所以：
    vintagedates 返回全部 realtime_start；带 realtime 窗口的 observations 返回与窗口相交的行并把起点截断到窗口；
    不带 realtime 的请求原样返回。与真实 FRED 对开放版本的语义一致。
    """

    def __init__(self, observations: list[dict[str, str]]) -> None:
        self._observations = observations

    def get(self, url: str, params: Mapping[str, str]) -> FredHttpResponse:
        if url.endswith("/series/vintagedates"):
            starts = sorted({item["realtime_start"] for item in self._observations})
            body = {"count": len(starts), "offset": 0, "vintage_dates": starts}
            return FredHttpResponse(200, json.dumps(body))
        rows = [dict(item) for item in self._observations]
        if "realtime_start" in params:
            window_start = params["realtime_start"]
            window_end = params["realtime_end"]
            rows = [
                {**item, "realtime_start": max(item["realtime_start"], window_start)}
                for item in rows
                if item["realtime_start"] <= window_end
            ]
        rows.sort(key=lambda item: (item["date"], item["realtime_start"]))
        offset = int(params.get("offset", "0"))
        limit = int(params.get("limit", "100000"))
        body = {"count": len(rows), "offset": offset, "observations": rows[offset : offset + limit]}
        return FredHttpResponse(200, json.dumps(body))


def _wx2_values() -> dict[str, Decimal | None]:
    with WX2.open(encoding="utf-8", newline="") as handle:
        return {
            row["observation_date"]: (None if row["value"] == "" else Decimal(row["value"]))
            for row in csv.DictReader(handle)
        }


def _alfred_current_values() -> dict[str, Decimal | None]:
    observations = json.loads(ALFRED.read_text(encoding="utf-8"))["observations"]
    fetched = fetch_observation_vintages(
        "CPIAUCSL", api_key="golden-fixture-no-network", http=_ReplayHttp(observations)
    )
    current: dict[str, Decimal | None] = {}
    for row in fetched.rows:
        if row["realtime_end"] != date(9999, 12, 31):
            continue
        observed = row["observation_date"]
        value = row["value"]
        assert isinstance(observed, date)
        assert value is None or isinstance(value, Decimal)
        current[observed.strftime("%Y%m%d")] = value
    return current


@pytest.mark.golden
def test_alfred_current_vintage_matches_wx2_cpiaucsl_2020_2025() -> None:
    wx2 = _wx2_values()
    alfred = _alfred_current_values()
    assert len(wx2) == len(alfred) == 72
    assert wx2.keys() == alfred.keys()
    mismatched = [(d, wx2[d], alfred[d]) for d in sorted(wx2) if wx2[d] != alfred[d]]
    assert mismatched == []


@pytest.mark.golden
def test_fixtures_stay_under_repo_file_limit() -> None:
    # AGENTS.md §10：单文件体积上限 512KB。
    for path in (WX2, ALFRED):
        assert path.stat().st_size < 512 * 1024, path.name
