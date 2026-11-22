"""本地研究库上的股票池与 ST 全量日期对拍，比对旧仓 wx2 快照的 sha256。

覆盖 golden fixture 的全部日期，而不是单个日期：
- ST：``ashare_st_wx2.json`` 的全部月末，``st_codes_at`` 逐日比对。
- 成分池：``constituents_wx2.json`` 的全部 (指数, 月末)。同一天若因区间重叠报
  ``InvalidQueryError``，记为失败并列出日期与重叠代码，不吞掉。
- all_a：对 ``all_a_wx2.json`` 的全部金样本日期，经 ``members_at(as_of=dt)`` 逐日比对。
  本地该日没有任何衍生指标行时，市值观测域缺失，与旧快照比对没有意义，记为缺数据并计入失败。
  缺数据日期过多（回填未完成）时整个用例 skip。

跳过（skip）不算通过，只说明本机还没有可对拍的数据。本文件不连接 wx2，金样本 sha256 来自 wx2 快照。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from quantagent.adapters.postgres.st import PostgresStStatusRepository
from quantagent.adapters.postgres.universe import PostgresUniverseRepository
from quantagent.domain.errors import EmptyDomainError, InvalidQueryError
from quantagent.platform.config import get_settings
from quantagent.platform.pg import connect, plane_configured

if TYPE_CHECKING:
    from collections.abc import Iterable

    import psycopg

    from quantagent.platform.config.settings import Settings

_GOLDEN_UNIVERSE = Path(__file__).parents[1] / "golden" / "universe"

# 少于这个数量的完整日期时 skip，避免几天的比对被当成全量验收。
_ALL_A_MIN_COMPLETE_DAYS = 100
_FAILURE_LIST_LIMIT = 20

# 旧表自身不一致的 7 个 all_a 例外日。与 tests/golden/test_all_a_universe_legacy.py 的
# KNOWN_DIFF_DATES 保持一致。这里是已知差异，不是放宽断言的理由。
_ALL_A_KNOWN_DIFF_DATES: frozenset[str] = frozenset(
    (
        "20210930",
        "20211231",
        "20220331",
        "20220630",
        "20260529",
        "20260617",
        "20260618",
    )
)


def _load(name: str) -> dict[str, Any]:
    loaded = json.loads((_GOLDEN_UNIVERSE / name).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _digest(codes: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(codes)).encode("utf-8")).hexdigest()


def _day(key: str) -> date:
    return datetime.strptime(key, "%Y%m%d").date()


def _open_local_read_only(settings: Settings) -> psycopg.Connection[Any]:
    conn = connect(settings, "src")
    # 会话级只读：即使误写 SQL，PG 也会拒绝。
    conn.read_only = True
    return conn


def _table_has_rows(conn: psycopg.Connection[Any], table: str) -> bool:
    # 表名是本文件内的常量字面量，不接受外部输入。
    with conn.cursor() as cur:
        cur.execute(f'SELECT EXISTS (SELECT 1 FROM "src_wind"."{table}")')
        row = cur.fetchone()
    assert row is not None
    return bool(row[0])


def _local_indicator_days(conn: psycopg.Connection[Any], lo: str, hi: str) -> frozenset[str]:
    """[lo, hi] 内本地有衍生指标行的日期。走 0024 的 TRADE_DT 索引。"""
    with conn.cursor() as cur:
        cur.execute(
            'SELECT DISTINCT "TRADE_DT" FROM "src_wind"."ASHAREEODDERIVATIVEINDICATOR" '
            'WHERE "TRADE_DT" BETWEEN %s AND %s',
            (lo, hi),
        )
        rows = cur.fetchall()
    return frozenset(str(day).strip() for (day,) in rows)


@pytest.mark.integration
def test_live_st_matches_legacy_snapshot_on_every_month_end() -> None:
    settings = get_settings()
    if not plane_configured(settings, "src"):
        pytest.skip("src 平面未配置 PG 连接串")
    expected: dict[str, dict[str, Any]] = _load("ashare_st_wx2.json")["expected"]
    conn = _open_local_read_only(settings)
    try:
        if not _table_has_rows(conn, "ASHAREST"):
            pytest.skip('src_wind."ASHAREST" 为空，无法全量对拍')
        repo = PostgresStStatusRepository(conn)
        mismatched: list[str] = []
        for key in sorted(expected):
            dt = _day(key)
            codes = repo.st_codes_at(as_of=dt, dt=dt)
            want = expected[key]
            if _digest(codes) != want["sha256"] or len(codes) != want["count"]:
                mismatched.append(f"{key}: local {len(codes)} vs wx2 {want['count']}")
    finally:
        conn.close()
    assert not mismatched, (
        f"ST 不一致 {len(mismatched)}/{len(expected)} 个月末: {mismatched[:_FAILURE_LIST_LIMIT]}"
    )


@pytest.mark.integration
def test_live_constituents_match_legacy_snapshot_on_every_month_end() -> None:
    settings = get_settings()
    if not plane_configured(settings, "src"):
        pytest.skip("src 平面未配置 PG 连接串")
    expected: dict[str, dict[str, dict[str, Any]]] = _load("constituents_wx2.json")["expected"]
    conn = _open_local_read_only(settings)
    try:
        if not _table_has_rows(conn, "AINDEXMEMBERS"):
            pytest.skip('src_wind."AINDEXMEMBERS" 为空，无法全量对拍')
        repo = PostgresUniverseRepository(conn)
        failures: list[str] = []
        checked = 0
        for index_code in sorted(expected):
            for key in sorted(expected[index_code]):
                checked += 1
                dt = _day(key)
                want = expected[index_code][key]
                try:
                    members = repo.members_at(
                        as_of=dt,
                        dt=dt,
                        universe_id=f"index:{index_code}",
                    )
                except (InvalidQueryError, EmptyDomainError) as exc:
                    # 区间重叠等报错原样记录，消息里已带日期与重叠代码。
                    failures.append(f"{index_code} {key}: {type(exc).__name__}: {exc}")
                    continue
                codes = [member.asset_id for member in members]
                if _digest(codes) != want["sha256"] or len(codes) != want["count"]:
                    failures.append(
                        f"{index_code} {key}: local {len(codes)} vs wx2 {want['count']}"
                    )
    finally:
        conn.close()
    assert not failures, (
        f"成分池不一致 {len(failures)}/{checked} 个 (指数, 月末): {failures[:_FAILURE_LIST_LIMIT]}"
    )


@pytest.mark.integration
def test_live_all_a_matches_legacy_snapshot_on_every_golden_day() -> None:
    settings = get_settings()
    if not plane_configured(settings, "src"):
        pytest.skip("src 平面未配置 PG 连接串")
    expected: dict[str, dict[str, Any]] = _load("all_a_wx2.json")["dates"]
    keys = sorted(expected)
    lo, hi = keys[0], keys[-1]
    conn = _open_local_read_only(settings)
    try:
        if not _table_has_rows(conn, "ASHAREDESCRIPTION"):
            pytest.skip('src_wind."ASHAREDESCRIPTION" 为空，无法计算规则池')
        if not _table_has_rows(conn, "ASHAREEODDERIVATIVEINDICATOR"):
            pytest.skip('src_wind."ASHAREEODDERIVATIVEINDICATOR" 为空，无法判断市值观测')
        present = _local_indicator_days(conn, lo, hi)
        missing = [key for key in keys if key not in present]
        if len(keys) - len(missing) < _ALL_A_MIN_COMPLETE_DAYS:
            pytest.skip(
                f"衍生指标缺数据 {len(missing)}/{len(keys)} 个日期，"
                f"有数据的日期不足 {_ALL_A_MIN_COMPLETE_DAYS} 个，回填未完成，不做全量对拍"
            )
        # 走正式读取路径 members_at(as_of=dt)，验收的是生产读法而不是测试里的另一套 SQL。
        repo = PostgresUniverseRepository(conn)
        passed = 0
        known = 0
        failures: list[str] = [f"{key}: 本地无衍生指标行（缺数据）" for key in missing]
        for key in keys:
            if key in present:
                dt = _day(key)
                try:
                    members = repo.members_at(as_of=dt, dt=dt, universe_id="all_a")
                except EmptyDomainError as exc:
                    failures.append(f"{key}: EmptyDomainError: {exc}")
                    continue
                codes = [member.asset_id for member in members]
                want = expected[key]
                matched = _digest(codes) == want["sha256"] and len(codes) == want["count"]
                if key in _ALL_A_KNOWN_DIFF_DATES:
                    known += 1
                    if matched:
                        failures.append(f"{key}: 已知例外日竟与 wx2 一致 (count {len(codes)})")
                elif matched:
                    passed += 1
                else:
                    failures.append(f"{key}: local {len(codes)} vs wx2 {want['count']}")
    finally:
        conn.close()
    summary = (
        f"all_a 金样本 {len(keys)} 个日期：缺数据 {len(missing)}，"
        f"通过 {passed}，已知例外 {known}，失败 {len(failures)}"
    )
    print(summary)
    assert not failures, f"{summary}；失败日期（前 {_FAILURE_LIST_LIMIT} 个）: " + "; ".join(
        failures[:_FAILURE_LIST_LIMIT]
    )
