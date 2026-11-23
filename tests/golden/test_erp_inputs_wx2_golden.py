"""中债 10Y 与中证全指 ERP：新仓读取端口对拍旧仓 wx2。

快照由旧仓代码原样运行生成（引擎注入 wx2，只读）：
- ``cgb_10y_wx2.json``：``MarketDataService.get_china_cgb_10y_yield_curve``，按年 count 与 sha256。
- ``erp_000985_wx2.json``：``EquityRiskPremiumService.get_history('20100101', ...)``，另存 2024 逐日值。
digest 定义写在各自的 provenance 里。ERP 在这里按旧仓定义用新端口的输出重算：
``ep = 100 / PE_TTM``（PE 非正丢弃）、同日 inner join 中债 10Y、``erp = ep - rf``。

wx2 快照之后 Wind 修订过部分 PE_TTM，新源镜像跟随源端（见 ADR src-mirror-follows-source）。
这些日期逐个登记在快照的 ``revised`` 里，digest 不含它们；测试同时断言登记的日期本地值
确实与 wx2 不同，避免登记表掩盖真实差异。
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from quantagent.adapters.postgres.index_valuation import PostgresIndexValuationRepository
from quantagent.adapters.postgres.macro import PostgresMacroRepository
from quantagent.platform.config import get_settings
from quantagent.platform.pg import connect

_DIR = Path(__file__).parent / "market_data"
_CGB = _DIR / "cgb_10y_wx2.json"
_ERP = _DIR / "erp_000985_wx2.json"
_AS_OF = date(2026, 11, 20)
_FILE_LIMIT_BYTES = 512 * 1024
_Q4 = Decimal("0.0001")


def _load(path: Path) -> dict[str, object]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _digest(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()


def _q4(value: Decimal | None) -> str:
    return "" if value is None else str(value.quantize(_Q4))


def _compare(expected: dict[str, dict[str, object]], local: dict[str, list[str]]) -> list[str]:
    problems = []
    for year in sorted(set(expected) | set(local)):
        info = expected.get(year)
        lines = local.get(year, [])
        if info is None:
            problems.append(f"{year}: 本地多出 {len(lines)} 行")
        elif len(lines) != info["count"] or _digest(lines) != info["sha256"]:
            problems.append(f"{year}: count wx2={info['count']} 本地={len(lines)}")
    return problems


@pytest.mark.golden
def test_fixtures_shape_and_size() -> None:
    for path in (_CGB, _ERP):
        assert path.stat().st_size < _FILE_LIMIT_BYTES
    erp = _load(_ERP)
    detail = erp["detail"]
    by_year = erp["by_year"]
    assert isinstance(detail, dict)
    assert isinstance(by_year, dict)
    assert _digest(detail["rows"]) == by_year[detail["year"]]["sha256"]
    revised = erp["revised"]
    assert isinstance(revised, dict)
    assert len(revised) == 254
    assert sum(int(v["count"]) for v in by_year.values()) + len(revised) == 4219


@pytest.mark.golden
@pytest.mark.integration
def test_cgb_10y_and_erp_match_wx2() -> None:
    conn = connect(get_settings(), "src")
    conn.read_only = True
    try:
        cgb = PostgresMacroRepository(conn).list_observations(
            as_of=_AS_OF, start=date(2002, 1, 1), end=_AS_OF, series_ids=("cn_cgb_10y",)
        )
        pe = PostgresIndexValuationRepository(conn).list_valuations(
            as_of=_AS_OF, start=date(2010, 1, 1), end=_AS_OF, wind_codes=("000985.CSI",)
        )
    finally:
        conn.close()

    cgb_lines: dict[str, list[str]] = defaultdict(list)
    rf: dict[date, Decimal | None] = {}
    for row in cgb:
        ymd = row.observation_date.strftime("%Y%m%d")
        cgb_lines[ymd[:4]].append(f"{ymd}|{_q4(row.value)}")
        rf[row.observation_date] = row.value
    cgb_by_year = _load(_CGB)["by_year"]
    assert isinstance(cgb_by_year, dict)
    problems = [f"中债 {p}" for p in _compare(cgb_by_year, cgb_lines)]

    erp = _load(_ERP)
    revised = erp["revised"]
    assert isinstance(revised, dict)
    erp_lines: dict[str, list[str]] = defaultdict(list)
    seen_revised: set[str] = set()
    for row in pe:
        r = rf.get(row.trade_dt)
        if row.pe_ttm is None or row.pe_ttm <= 0 or r is None:
            continue
        ymd = row.trade_dt.strftime("%Y%m%d")
        if ymd in revised:
            seen_revised.add(ymd)
            if Decimal(revised[ymd]["wx2_pe_ttm"]) == row.pe_ttm:
                problems.append(f"ERP {ymd}: 登记为已修订，但本地 PE_TTM 与 wx2 相同")
            continue
        ep = 100.0 / float(row.pe_ttm)
        erp_lines[ymd[:4]].append(f"{ymd}|{ep:.10f}|{_q4(r)}|{ep - float(r):.10f}")
    missing = sorted(set(revised) - seen_revised)
    if missing:
        problems.append(f"ERP 登记的修订日期本地缺失: {missing[:5]}")
    erp_by_year = erp["by_year"]
    detail = erp["detail"]
    assert isinstance(erp_by_year, dict)
    assert isinstance(detail, dict)
    erp_problems = _compare(erp_by_year, erp_lines)
    if erp_problems:
        expected = set(detail["rows"])
        got = set(erp_lines[detail["year"]])
        erp_problems += [f"  wx2 有本地无 {x}" for x in sorted(expected - got)[:5]]
        erp_problems += [f"  本地有 wx2 无 {x}" for x in sorted(got - expected)[:5]]
    problems += [f"ERP {p}" for p in erp_problems]
    assert not problems, "\n".join(problems[:20])
