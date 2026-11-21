"""本地研究库上的股票池与 ST 全量日期对拍，比对旧仓 wx2 快照的 sha256。

覆盖 golden fixture 的全部日期，而不是单个日期：
- ST：``ashare_st_wx2.json`` 的全部月末，``st_codes_at`` 逐日比对。
- 成分池：``constituents_wx2.json`` 的全部 (指数, 月末)。同一天若因区间重叠报
  ``InvalidQueryError``，记为失败并列出日期与重叠代码，不吞掉。
- all_a：只比对衍生指标已完整的日期。完整指本地与 wx2 的
  ``ASHAREEODDERIVATIVEINDICATOR`` 在该 ``TRADE_DT`` 的行数相同且非零。衍生指标缺行时，
  市值观测域不完整，与旧快照比对没有意义，所以这些日期不计入。

跳过（skip）不算通过，只说明本机还没有可对拍的数据。wx2 只用于读取衍生指标行数，且只发 SELECT。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from importlib import import_module
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


def _local_indicator_counts(conn: psycopg.Connection[Any], lo: str, hi: str) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            'SELECT "TRADE_DT", count(*) FROM "src_wind"."ASHAREEODDERIVATIVEINDICATOR" '
            'WHERE "TRADE_DT" >= %s AND "TRADE_DT" <= %s GROUP BY 1',
            (lo, hi),
        )
        rows = cur.fetchall()
    return {str(day).strip(): int(count) for day, count in rows}


def _wx2_indicator_counts(settings: Settings, lo: str, hi: str) -> dict[str, int]:
    """wx2 上 ``ASHAREEODDERIVATIVEINDICATOR`` 的日行数。只发一条 SELECT。

    tds_version 与 login_timeout 与 ``wgc_legacy`` 的连接保持一致。
    """
    pymssql = import_module("pymssql")
    conn = pymssql.connect(
        server=settings.legacy_mssql_host,
        port=str(settings.legacy_mssql_port),
        user=settings.legacy_mssql_user,
        password=settings.legacy_mssql_password.get_secret_value(),
        database=settings.legacy_mssql_database,
        tds_version="7.0",
        login_timeout=15,
        # 全表 GROUP BY 约 2,500 万行，超时放宽到 10 分钟。
        timeout=600,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT TRADE_DT, COUNT(*) FROM dbo.ASHAREEODDERIVATIVEINDICATOR "
                "WHERE TRADE_DT >= %s AND TRADE_DT <= %s GROUP BY TRADE_DT",
                (lo, hi),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return {str(day).strip(): int(count) for day, count in rows}


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
def test_live_all_a_matches_legacy_snapshot_on_complete_indicator_days() -> None:
    settings = get_settings()
    if not plane_configured(settings, "src"):
        pytest.skip("src 平面未配置 PG 连接串")
    if not settings.legacy_mssql_configured:
        pytest.skip("wx2 未配置，无法比对衍生指标行数以判定完整日期")
    expected: dict[str, dict[str, Any]] = _load("all_a_wx2.json")["dates"]
    keys = sorted(expected)
    lo, hi = keys[0], keys[-1]
    wx2_counts = _wx2_indicator_counts(settings, lo, hi)
    conn = _open_local_read_only(settings)
    try:
        if not _table_has_rows(conn, "ASHAREDESCRIPTION"):
            pytest.skip('src_wind."ASHAREDESCRIPTION" 为空，无法计算规则池')
        if not _table_has_rows(conn, "ASHAREEODDERIVATIVEINDICATOR"):
            pytest.skip('src_wind."ASHAREEODDERIVATIVEINDICATOR" 为空，无法判断市值观测')
        local_counts = _local_indicator_counts(conn, lo, hi)
        complete = [
            key
            for key in keys
            if local_counts.get(key, 0) > 0 and local_counts.get(key, 0) == wx2_counts.get(key, 0)
        ]
        if len(complete) < _ALL_A_MIN_COMPLETE_DAYS:
            pytest.skip(
                f"衍生指标完整日期只有 {len(complete)} 个（需要 >= {_ALL_A_MIN_COMPLETE_DAYS}），"
                f"回填未完成，不做全量对拍"
            )
        repo = PostgresUniverseRepository(conn)
        passed = 0
        known_in_complete = 0
        failures: list[str] = []
        for key in complete:
            dt = _day(key)
            members = repo.members_at(as_of=dt, dt=dt, universe_id="all_a")
            codes = [member.asset_id for member in members]
            want = expected[key]
            matched = _digest(codes) == want["sha256"] and len(codes) == want["count"]
            if key in _ALL_A_KNOWN_DIFF_DATES:
                known_in_complete += 1
                if matched:
                    failures.append(f"{key}: 已知例外日竟与 wx2 一致 (count {len(codes)})")
                else:
                    passed += 1
            elif matched:
                passed += 1
            else:
                failures.append(f"{key}: local {len(codes)} vs wx2 {want['count']}")
    finally:
        conn.close()
    summary = (
        f"all_a 完整日期 {len(complete)}/{len(keys)}（其中已知例外日 {known_in_complete}），"
        f"通过 {passed}，失败 {len(failures)}"
    )
    print(summary)
    assert not failures, f"{summary}；失败日期（前 {_FAILURE_LIST_LIMIT} 个）: " + "; ".join(
        failures[:_FAILURE_LIST_LIMIT]
    )
