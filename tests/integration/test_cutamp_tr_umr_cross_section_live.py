"""cutamp 与 tr_umr 在 2024-01-05 全截面上与 wx2 旧表逐只比对。

旧值来自 ``tests/golden/market_data/*_wx2_20240105.json``，抓取 SQL 写在各自的 provenance 里。
计算走正式读取路径：``PostgresDailyPriceRepository`` / ``PostgresIndexReturnRepository`` 配合
``load_*_visibility()``，再交给 ``build_cutamp_values`` / ``build_tr_umr_values`` 产出长表行。
tr_umr 的开市日来自本地 lake 的 SSE 日历，与 ``cli/tr_umr_materialize.py`` 相同。

比对精度：长表 ``FeatureValue.value`` 是 float，这里先把 float 的 repr 转回 Decimal，
再按 ROUND_HALF_UP 量化到旧表的存储精度。比的是系统真正写出去的值，不是中间 Decimal。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.daily_prices import (
    PostgresDailyPriceRepository,
    load_price_visibility,
)
from quantagent.adapters.postgres.index_returns import (
    PostgresIndexReturnRepository,
    load_index_visibility,
)
from quantagent.adapters.postgres.src_dml import assert_src_dml_sql
from quantagent.domain.calendar import open_dates
from quantagent.features.library.price.tr_umr import BENCHMARK, LOOKBACK
from quantagent.features.panel.cutamp import build_cutamp_values
from quantagent.features.panel.tr_umr import build_tr_umr_values
from quantagent.platform.config import get_settings
from quantagent.platform.pg import connect
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

if TYPE_CHECKING:
    from collections.abc import Mapping

    import psycopg

    from quantagent.domain.feature_value import FeatureValue

_GOLDEN = Path(__file__).parents[1] / "golden" / "market_data"
_CUTAMP_FIXTURE = _GOLDEN / "cutamp_wx2_20240105.json"
_TR_UMR_FIXTURE = _GOLDEN / "tr_umr_wx2_20240105.json"

_AS_OF = date(2024, 1, 5)
_CUTAMP_READ_START = date(2023, 11, 1)
_CUTAMP_SCALE = Decimal("0.000001")
_TR_UMR_SCALE = Decimal("0.00000001")
_EXCHANGE = "SSE"
_CALENDAR_PAD_DAYS = 240
_FAILURE_LIST_LIMIT = 20

# tr_umr 2024-01-05 已知的 3 只不一致。来源：docs/migration/wind-pipeline-handoff.md 第 68-71 行。
# 000717.SZ 与 000016.SZ 的复权价有 0.0001 的差别，涨跌幅相同；
# 000078.SZ 的复权价是常数比例，真实波幅里这个比例会消掉，因子只剩 7e-9。
# 这是旧表与本仓输入不同造成的差异，不是放宽断言的理由。三只必须仍然不一致，否则测试失败。
_TR_UMR_KNOWN_DIFF: frozenset[str] = frozenset(("000717.SZ", "000016.SZ", "000078.SZ"))

# cutamp 的两类缺失是已知且可解释的，不是实现漏算。它们在 wx2 有值，本地不产出：
# (a) 北交所旧代码：wx2 旧表保存的是 2025 年北交所改码前的旧代码（.BJ 后缀）。本地
#     ASHAREDESCRIPTION 里没有这些旧代码，all_a 本就排除北交所，所以不产出。
# (b) 截面日前已退市：wx2 旧表给已退市股票留了值，新实现不填充。本地描述表的
#     S_INFO_DELISTDATE 非空且早于截面日。
# 两类之外的缺失仍然判失败。
_AS_OF_YMD = "20240105"
_DESCRIBE_SQL = assert_src_dml_sql(
    'SELECT "S_INFO_WINDCODE", "S_INFO_DELISTDATE"'
    ' FROM src_wind."ASHAREDESCRIPTION"'
    ' WHERE "S_INFO_WINDCODE" = ANY(%s)'
)


def _load_expected(path: Path, value_key: str) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["rows"]
    assert all(row["trade_dt"] == "2024-01-05" for row in rows)
    expected = {row["wind_code"]: row[value_key] for row in rows}
    # 一只股票只能有一行，否则比对口径不清。
    assert len(expected) == len(rows)
    return expected


def _quantize_float(value: float, scale: Decimal) -> Decimal:
    return Decimal(repr(value)).quantize(scale, rounding=ROUND_HALF_UP)


def _compare(
    expected: Mapping[str, str],
    local: Mapping[str, Decimal],
    scale: Decimal,
) -> tuple[list[str], list[str], list[str]]:
    """返回 (不一致, 新实现没产出, 新实现多产出) 三组，按代码排序。"""
    mismatches: list[str] = []
    missing: list[str] = []
    for code in sorted(expected):
        want = Decimal(expected[code]).quantize(scale, rounding=ROUND_HALF_UP)
        if code not in local:
            missing.append(code)
        elif local[code] != want:
            mismatches.append(f"{code}: local {local[code]} vs wx2 {expected[code]}")
    extra = sorted(set(local) - set(expected))
    return mismatches, missing, extra


def _format_failure(
    *,
    name: str,
    expected_count: int,
    local_count: int,
    mismatches: list[str],
    missing: list[str],
    extra: list[str],
) -> str:
    lines = [
        f"{name} 2024-01-05 全截面：wx2 {expected_count} 行，本地产出 {local_count} 行",
        f"不一致 {len(mismatches)}，wx2 有本地没产出 {len(missing)}，本地多出 {len(extra)}",
    ]
    if mismatches:
        lines.append(f"不一致（前 {_FAILURE_LIST_LIMIT}）:")
        lines.extend(f"  {item}" for item in mismatches[:_FAILURE_LIST_LIMIT])
    if missing:
        lines.append(
            f"wx2 有、本地没产出（前 {_FAILURE_LIST_LIMIT}）: {missing[:_FAILURE_LIST_LIMIT]}"
        )
    if extra:
        lines.append(f"本地多出（前 {_FAILURE_LIST_LIMIT}）: {extra[:_FAILURE_LIST_LIMIT]}")
    return "\n".join(lines)


def _describe(conn: psycopg.Connection[Any], codes: tuple[str, ...]) -> dict[str, str | None]:
    """返回本地 ASHAREDESCRIPTION 里存在的代码到 S_INFO_DELISTDATE 的映射。"""
    with conn.cursor() as cur:
        cur.execute(_DESCRIBE_SQL, (list(codes),))
        return {str(code): delist for code, delist in cur.fetchall()}


def _explained_missing(
    expected: Mapping[str, str],
    described: Mapping[str, str | None],
) -> tuple[set[str], set[str]]:
    """返回 (北交所旧代码, 截面日前已退市) 两类缺失代码。"""
    bj_old_code = {code for code in expected if code.endswith(".BJ") and code not in described}
    delisted = {code for code, delist in described.items() if delist and delist < _AS_OF_YMD}
    return bj_old_code, delisted


@pytest.mark.integration
def test_cutamp_cross_section_matches_wx2_20240105() -> None:
    expected = _load_expected(_CUTAMP_FIXTURE, "cutamp")
    codes = tuple(sorted(expected))

    conn = connect(get_settings(), "src")
    conn.read_only = True
    try:
        prices = PostgresDailyPriceRepository(conn).list_prices(
            as_of=_AS_OF,
            start=_CUTAMP_READ_START,
            end=_AS_OF,
            wind_codes=codes,
        )
        described = _describe(conn, codes)
    finally:
        conn.close()

    rows: tuple[FeatureValue, ...] = build_cutamp_values(
        prices,
        contract=load_price_visibility(),
        start=_AS_OF,
        end=_AS_OF,
        computed_at=datetime(2026, 11, 22),
        run_id="golden-cutamp-20240105",
    )
    # 长表 value = SIGN * raw，SIGN 为 -1。旧表存的是 raw，所以比对前取反。
    local: dict[str, Decimal] = {}
    for row in rows:
        assert row.event_dt == _AS_OF
        assert row.asset_id not in local
        local[row.asset_id] = _quantize_float(-row.value, _CUTAMP_SCALE)

    mismatches, missing, extra = _compare(expected, local, _CUTAMP_SCALE)
    bj_old_code, delisted = _explained_missing(expected, described)
    unexplained = [code for code in missing if code not in bj_old_code | delisted]
    print(
        f"\ncutamp 2024-01-05: wx2 {len(expected)} 行，本地 {len(local)} 行，"
        f"一致 {len(expected) - len(mismatches) - len(missing)}，不一致 {len(mismatches)}，"
        f"缺失 {len(missing)}（北交所旧代码 {len(bj_old_code)}，截面日前已退市 {len(delisted)}，"
        f"未解释 {len(unexplained)}），多出 {len(extra)}"
    )
    assert not (mismatches or unexplained or extra), _format_failure(
        name="cutamp",
        expected_count=len(expected),
        local_count=len(local),
        mismatches=mismatches,
        missing=unexplained,
        extra=extra,
    )


@pytest.mark.integration
def test_tr_umr_cross_section_matches_wx2_20240105() -> None:
    expected = _load_expected(_TR_UMR_FIXTURE, "tr_umr")
    codes = tuple(sorted(expected))

    paths = resolve_var_paths(get_settings(), repo_root=detect_repo_root())
    days = LakeCalendarRepository(paths.lake / "std" / "trade_calendar").list_days(
        as_of=_AS_OF,
        exchange=_EXCHANGE,
        start=_AS_OF - timedelta(days=_CALENDAR_PAD_DAYS),
        end=_AS_OF,
    )
    opens = open_dates(days)
    # 与 cli/tr_umr_materialize.py 的 _read_start 相同：第一个截面日前 68 个开市日。
    cross_index = opens.index(_AS_OF)
    read_start = opens[cross_index - (LOOKBACK - 1)]

    conn = connect(get_settings(), "src")
    conn.read_only = True
    try:
        prices = PostgresDailyPriceRepository(conn).list_prices(
            as_of=_AS_OF,
            start=read_start,
            end=_AS_OF,
            wind_codes=codes,
        )
        index_returns = PostgresIndexReturnRepository(conn).list_returns(
            as_of=_AS_OF,
            start=read_start,
            end=_AS_OF,
            wind_codes=(BENCHMARK,),
        )
    finally:
        conn.close()

    rows: tuple[FeatureValue, ...] = build_tr_umr_values(
        prices,
        index_returns,
        opens,
        price_contract=load_price_visibility(),
        index_contract=load_index_visibility(),
        start=_AS_OF,
        end=_AS_OF,
        computed_at=datetime(2026, 11, 22),
        run_id="golden-tr-umr-20240105",
    )
    local: dict[str, Decimal] = {}
    for row in rows:
        assert row.event_dt == _AS_OF
        assert row.asset_id not in local
        local[row.asset_id] = _quantize_float(row.value, _TR_UMR_SCALE)

    mismatches, missing, extra = _compare(expected, local, _TR_UMR_SCALE)
    mismatch_codes = {item.split(":", 1)[0] for item in mismatches}

    # 已知差异必须仍然不一致。若某只变成一致，说明上游或实现已变，需要人工复核后再改常量。
    unexpected = [item for item in mismatches if item.split(":", 1)[0] not in _TR_UMR_KNOWN_DIFF]
    stale_known = sorted(_TR_UMR_KNOWN_DIFF - mismatch_codes)
    print(
        f"\ntr_umr 2024-01-05: wx2 {len(expected)} 行，本地 {len(local)} 行，"
        f"一致 {len(expected) - len(mismatches) - len(missing)}，"
        f"不一致 {len(mismatches)}（其中已知 {len(mismatch_codes & _TR_UMR_KNOWN_DIFF)}，"
        f"未知 {len(unexpected)}），缺失 {len(missing)}，多出 {len(extra)}"
    )
    assert not (unexpected or missing or extra or stale_known), (
        _format_failure(
            name="tr_umr",
            expected_count=len(expected),
            local_count=len(local),
            mismatches=unexpected,
            missing=missing,
            extra=extra,
        )
        + f"\n已知差异中已不再不一致的（需复核后移出 _TR_UMR_KNOWN_DIFF）: {stale_known}"
    )
