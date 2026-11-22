"""旧仓 ``MarketDataService.get_index_eod_returns`` 与新仓 ``IndexReturnRepository`` 的指数涨跌幅对拍。

快照 ``index_returns_wx2.json`` 按 (指数, 年) 保存 count 与 sha256，digest 的定义写在 provenance 里。
另存 ``000985.CSI`` 2024 的逐日值，用来在不一致时定位到具体日期。
指数范围取旧仓现役调用方实际传入的代码（见 provenance.codes_evidence）。
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import pytest

from quantagent.adapters.postgres.index_returns import PostgresIndexReturnRepository
from quantagent.platform.config import get_settings
from quantagent.platform.pg import connect

_FIXTURE = Path(__file__).parent / "market_data" / "index_returns_wx2.json"
_CODES = ("000985.CSI", "h30269.CSI")
_START = date(2018, 1, 2)
_AS_OF = date(2026, 11, 6)
_FILE_LIMIT_BYTES = 512 * 1024
_LINE_LIMIT = 20


def _payload() -> dict[str, object]:
    loaded = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _digest(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _pairs_by_group(
    rows: list[tuple[str, str, str]],
) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """(trade_dt YYYYMMDD, code, pct 文本) → {(code, year): [(trade_dt, pct)]}，按日期升序。"""
    groups: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for trade_dt, code, pct in rows:
        groups[(code, trade_dt[:4])].append((trade_dt, pct))
    for items in groups.values():
        items.sort()
    return groups


@pytest.mark.golden
def test_index_returns_fixture_shape_and_size() -> None:
    assert _FIXTURE.stat().st_size < _FILE_LIMIT_BYTES
    payload = _payload()
    by_year = payload["by_year"]
    assert isinstance(by_year, dict)
    assert set(by_year) == set(_CODES)
    total = sum(int(info["count"]) for years in by_year.values() for info in years.values())
    assert total == 4290
    detail = payload["detail"]
    assert isinstance(detail, dict)
    info = by_year[detail["index_code"]][detail["year"]]
    assert len(detail["rows"]) == info["count"]
    # 逐日明细必须与它所在组的 digest 自洽，否则失败时的逐日定位会误导。
    detail_lines = [f"{d}|{p}" for d, p in detail["rows"]]
    assert _digest(detail_lines) == info["sha256"]


@pytest.mark.golden
@pytest.mark.integration
def test_index_returns_by_year_digest_matches_wx2() -> None:
    payload = _payload()
    by_year = payload["by_year"]
    detail = payload["detail"]
    assert isinstance(by_year, dict)
    assert isinstance(detail, dict)

    conn = connect(get_settings(), "src")
    conn.read_only = True
    try:
        local_rows = PostgresIndexReturnRepository(conn).list_returns(
            as_of=_AS_OF,
            start=_START,
            end=_AS_OF,
            wind_codes=_CODES,
        )
    finally:
        conn.close()

    raw = [
        (
            row.trade_dt.strftime("%Y%m%d"),
            row.wind_code,
            "" if row.pct_change is None else str(row.pct_change),
        )
        for row in local_rows
    ]
    groups = _pairs_by_group(raw)

    problems: list[str] = []
    expected_keys = {(code, year) for code, years in by_year.items() for year in years}
    local_keys = set(groups)
    for code, year in sorted(expected_keys - local_keys):
        problems.append(f"{code} {year}: 本地无数据，wx2 有 {by_year[code][year]['count']} 行")
    for code, year in sorted(local_keys - expected_keys):
        problems.append(f"{code} {year}: 本地多出 {len(groups[(code, year)])} 行，wx2 无此年")

    matched = 0
    for code, years in sorted(by_year.items()):
        for year, info in sorted(years.items()):
            if (code, year) not in groups:
                continue
            items = groups[(code, year)]
            local_digest = _digest([f"{d}|{p}" for d, p in items])
            if len(items) == info["count"] and local_digest == info["sha256"]:
                matched += 1
                continue
            problems.append(
                f"{code} {year}: count wx2={info['count']} 本地={len(items)}；"
                f"sha256 wx2={str(info['sha256'])[:12]} 本地={local_digest[:12]}"
            )
            if code == detail["index_code"] and year == detail["year"]:
                problems.extend(_daily_diff(detail["rows"], items))

    print(
        f"\n指数涨跌幅对拍：{len(expected_keys)} 个 (指数, 年) 组，"
        f"digest 一致 {matched} 组，本地共 {len(local_rows)} 行。"
    )
    assert not problems, "指数涨跌幅不一致:\n" + "\n".join(problems[:_LINE_LIMIT])


def _daily_diff(expected_rows: object, local_items: list[tuple[str, str]]) -> list[str]:
    assert isinstance(expected_rows, list)
    expected = {str(d): str(p) for d, p in expected_rows}
    local = dict(local_items)
    out: list[str] = []
    for day in sorted(set(expected) | set(local)):
        if day not in local:
            out.append(f"  {day}: wx2={expected[day]!r} 本地缺失")
        elif day not in expected:
            out.append(f"  {day}: 本地={local[day]!r} wx2 无此日")
        elif expected[day] != local[day]:
            out.append(f"  {day}: wx2={expected[day]!r} 本地={local[day]!r}")
    return out
