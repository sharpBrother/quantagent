"""all_a 与旧仓 wx2 快照对拍。

快照：``tests/golden/universe/``。规则池来自 ``ashare_description_wx2.json``，
缺市值日来自 ``all_a_mv_missing_wx2.json``，旧成员 sha256 来自 ``all_a_wx2.json``。

``KNOWN_DIFF_DATES`` 是已知不一致的日期，不是放宽断言的理由。断言要求不一致的日期
恰好是这 7 天，既不能多也不能少。新增不一致必须停下查清，不能加进这个常量。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from quantagent.adapters.postgres.universe import parse_ymd_optional
from quantagent.domain.universe import ListingRow, all_a_listed, all_a_members

_DIR = Path(__file__).parent / "universe"

# 旧表 2026-08-11/12 重写这四天时，保留了当日市值为空的 000670.SZ、002260.SZ，
# 没有套用 canonical 市值过滤，所以旧成员比规则多出这两只。
_REWRITE_KEEPS_NULL_MV = ("20210930", "20211231", "20220331", "20220630")
# 旧表 2026-08-07 重写时混入 317 只北交所股票（exchange_market = BSE）。
_REWRITE_INCLUDES_BSE = ("20260529",)
# 旧表 2026-08-07 重写，比规则多 68/70 只，原因未查明。旧仓自身不一致，按旧仓处理。
_UNEXPLAINED_EXTRA = ("20260617", "20260618")

KNOWN_DIFF_DATES: frozenset[str] = frozenset(
    (*_REWRITE_KEEPS_NULL_MV, *_REWRITE_INCLUDES_BSE, *_UNEXPLAINED_EXTRA)
)


def _load(name: str) -> dict[str, Any]:
    loaded = json.loads((_DIR / name).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _listings(rows: list[list[str | None]]) -> tuple[ListingRow, ...]:
    return tuple(
        ListingRow(
            asset_id=str(code),
            list_date=parse_ymd_optional(listed, "S_INFO_LISTDATE"),
            delist_date=parse_ymd_optional(delisted, "S_INFO_DELISTDATE"),
            exchange_market=None if exchange is None else str(exchange),
        )
        for code, listed, delisted, exchange in rows
    )


def _digest(codes: list[str]) -> str:
    return hashlib.sha256("\n".join(codes).encode("utf-8")).hexdigest()


@pytest.mark.golden
def test_all_a_matches_legacy_snapshot_except_known_dates() -> None:
    description = _load("ashare_description_wx2.json")
    missing_by_day: dict[str, list[str]] = _load("all_a_mv_missing_wx2.json")["dates"]
    expected: dict[str, dict[str, Any]] = _load("all_a_wx2.json")["dates"]

    listings = _listings(description["rows"])
    mismatched: list[str] = []
    for day in sorted(expected):
        dt = datetime.strptime(day, "%Y%m%d").date()
        listed = all_a_listed(listings, dt=dt)
        observed = listed - set(missing_by_day.get(day, []))
        members = all_a_members(listings, dt=dt, observed=observed)
        codes = [member.asset_id for member in members]
        if _digest(codes) != expected[day]["sha256"] or len(codes) != expected[day]["count"]:
            mismatched.append(day)

    assert sorted(mismatched) == sorted(KNOWN_DIFF_DATES), (
        f"新增的不一致日期: {sorted(set(mismatched) - KNOWN_DIFF_DATES)}; "
        f"已知但本次一致的日期: {sorted(KNOWN_DIFF_DATES - set(mismatched))}"
    )


@pytest.mark.golden
def test_known_diff_dates_are_all_present_in_snapshot() -> None:
    expected = _load("all_a_wx2.json")["dates"]
    assert set(expected) >= KNOWN_DIFF_DATES
