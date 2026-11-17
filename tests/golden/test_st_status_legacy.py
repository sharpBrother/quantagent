"""ST 当日判定与旧仓 wx2 快照对拍。

快照：``tests/golden/universe/ashare_st_wx2.json``，只读采集，采集日 2026-11-17。
旧口径：``strategy/growth_stock.py _get_st_stocks``，即
``ENTRY_DT <= dt AND (REMOVE_DT IS NULL OR REMOVE_DT > dt)``，按代码去重。
断言每个月末开市日的代码数与 sha256 都与快照相等。不设已知差异日期，任何不一致都停下查清，
不加白名单放宽。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from quantagent.domain.universe import StRow, st_codes

_FIXTURE = Path(__file__).parent / "universe" / "ashare_st_wx2.json"


def _load() -> dict[str, Any]:
    loaded = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _ymd(raw: str) -> datetime:
    return datetime.strptime(raw, "%Y%m%d")


def _rows(raw: list[list[str | None]]) -> tuple[StRow, ...]:
    out: list[StRow] = []
    for code, entry, remove in raw:
        assert code is not None
        assert entry is not None
        out.append(
            StRow(
                asset_id=code,
                entry_date=_ymd(entry).date(),
                remove_date=None if remove is None else _ymd(remove).date(),
            )
        )
    return tuple(out)


def _digest(codes: list[str]) -> str:
    return hashlib.sha256("\n".join(codes).encode("utf-8")).hexdigest()


@pytest.mark.golden
def test_st_codes_match_legacy_snapshot_on_every_month_end() -> None:
    fixture = _load()
    rows = _rows(fixture["rows"])
    expected: dict[str, dict[str, Any]] = fixture["expected"]
    mismatched: list[str] = []
    for day, want in sorted(expected.items()):
        dt = _ymd(day).date()
        codes = sorted(st_codes(rows, dt=dt))
        if len(codes) != want["count"] or _digest(codes) != want["sha256"]:
            mismatched.append(f"{day}: got {len(codes)} want {want['count']}")
    assert mismatched == [], f"与 wx2 快照不一致: {mismatched}"


@pytest.mark.golden
def test_snapshot_covers_2010_01_to_2026_10_month_ends() -> None:
    expected: dict[str, dict[str, Any]] = _load()["expected"]
    keys = sorted(expected)
    assert len(keys) == 202
    assert keys[0] == "20100129"
    assert keys[-1] == "20261030"
