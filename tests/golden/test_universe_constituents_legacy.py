"""指数成分与旧仓 wx2 快照对拍。

快照：``tests/golden/universe/constituents_wx2.json``，由父代理采集，只读。
旧口径：``alpha_factory/data_gateway.py get_index_members``，
``S_CON_INDATE <= dt AND (S_CON_OUTDATE IS NULL OR S_CON_OUTDATE >= dt)``。
断言每个指数、每个月末日期的成员数与 sha256 都与快照相等。不设已知差异日期，
任何不一致都停下查清，不加白名单放宽。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from quantagent.domain.universe import ConstituentRow, constituent_members

_FIXTURE = Path(__file__).parent / "universe" / "constituents_wx2.json"


def _load() -> dict[str, Any]:
    loaded = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _rows(raw: list[list[str | None]]) -> tuple[ConstituentRow, ...]:
    return tuple(
        ConstituentRow(
            index_code=str(index_code),
            asset_id=str(asset_id),
            in_date=None if in_date is None else _ymd(in_date),
            out_date=None if out_date is None else _ymd(out_date),
        )
        for index_code, asset_id, in_date, out_date in raw
    )


def _ymd(raw: str) -> date:
    return datetime.strptime(raw, "%Y%m%d").date()


def _digest(codes: list[str]) -> str:
    return hashlib.sha256("\n".join(codes).encode("utf-8")).hexdigest()


@pytest.mark.golden
def test_constituents_match_legacy_snapshot_for_all_indexes_and_month_ends() -> None:
    fixture = _load()
    rows = _rows(fixture["rows"])
    expected: dict[str, dict[str, dict[str, Any]]] = fixture["expected"]

    mismatched: list[str] = []
    for index_code, by_day in sorted(expected.items()):
        universe_id = f"index:{index_code}"
        for day, want in sorted(by_day.items()):
            dt = datetime.strptime(day, "%Y%m%d").date()
            members = constituent_members(rows, universe_id=universe_id, dt=dt)
            codes = [member.asset_id for member in members]
            if len(codes) != want["count"] or _digest(codes) != want["sha256"]:
                mismatched.append(f"{index_code} {day}")

    assert mismatched == [], f"与 wx2 快照不一致: {mismatched}"


@pytest.mark.golden
def test_hs300_2024_01_31_has_300_members() -> None:
    rows = _rows(_load()["rows"])
    members = constituent_members(
        rows,
        universe_id="index:000300.SH",
        dt=datetime.strptime("20240131", "%Y%m%d").date(),
    )
    assert len(members) == 300
    assert _digest([m.asset_id for m in members]) == (
        "5d3c6b8b603a42def5f3eddce7a18df91fa97acd348e7778415c3fb186920531"
    )
