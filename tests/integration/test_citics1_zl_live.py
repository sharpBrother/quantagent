"""本地研究库上的中信一级成分（``AINDEXMEMBERSCITICSZL``）与 wx2 月末快照对拍。
快照：``tests/golden/universe/citics1_zl_wx2.json``，2026-11-22 只读抓取，覆盖 2018-01 至 2026-10 的
每个自然月最后一个开市日。每个月末存了成员对数、按 ``行业|股票`` 排序后的 sha256，以及当月出现的行业代码。
逐行业调用正式读取路径 ``PostgresUniverseRepository.members_at(universe_id="citics1:<行业>")``，
拼成 ``行业|股票`` 列表后再与快照比对。快照里的行业列表来自 wx2 当月命中行，本地若多出快照没有的行业，
由对数与 sha256 的不一致发现。
同一股票同日命中多个行业，或同一行业区间重叠，在读取路径会报错。这里记为失败并列出，不吞掉。
跳过（skip）不算通过，只说明本机还没有可对拍的数据。本文件不连接 wx2。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from quantagent.adapters.postgres.universe import PostgresUniverseRepository
from quantagent.domain.errors import EmptyDomainError, InvalidQueryError
from quantagent.platform.config import get_settings
from quantagent.platform.pg import connect, plane_configured

if TYPE_CHECKING:
    import psycopg

    from quantagent.platform.config.settings import Settings

_FIXTURE = Path(__file__).parents[1] / "golden" / "universe" / "citics1_zl_wx2.json"
_TABLE = "AINDEXMEMBERSCITICSZL"
_FAILURE_LIST_LIMIT = 20

# wx2 快照里有、当前 Wind 源已不再提供的 5 行（2026-11-22 核对）。本地按源镜像，没有这些行；
# 采集游标已越过同一 OPDATE 下 OBJECT_ID 更大的行（{8BDD6D79-...}603336.SH），说明源端不再返回它们，
# 不是漏采。比对时把它们在有效区间内补回本地列表以重建 wx2 的 digest，并断言本地确实没有这些 OBJECT_ID。
# (OBJECT_ID, 行业, 股票, S_CON_INDATE, S_CON_OUTDATE)
_WX2_ONLY_ROWS: tuple[tuple[str, str, str, str, str | None], ...] = (
    (
        "{56FFFD97-1E2E-11EF-9699-FC3497B90A6F}001246.SZ",
        "CI005003.WI",
        "001246.SZ",
        "20221201",
        None,
    ),
    (
        "{8BDD6D6D-C2B1-11F1-9AC6-FC3497B90A3F}001381.SZ",
        "CI005006.WI",
        "001381.SZ",
        "20261008",
        None,
    ),
    (
        "{8BDD6D6F-C2B1-11F1-9AC6-FC3497B90A3F}301718.SZ",
        "CI005026.WI",
        "301718.SZ",
        "20261008",
        None,
    ),
    (
        "{8BDD6D71-C2B1-11F1-9AC6-FC3497B90A3F}301569.SZ",
        "CI005018.WI",
        "301569.SZ",
        "20261008",
        None,
    ),
    (
        "{8BDD6D73-C2B1-11F1-9AC6-FC3497B90A3F}301660.SZ",
        "CI005025.WI",
        "301660.SZ",
        "20261008",
        None,
    ),
)


def _wx2_only_lines(key: str) -> list[str]:
    return [
        f"{industry}|{code}"
        for _, industry, code, indate, outdate in _WX2_ONLY_ROWS
        if indate <= key and (outdate is None or outdate >= key)
    ]


def _load() -> dict[str, Any]:
    loaded = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _day(key: str) -> date:
    return datetime.strptime(key, "%Y%m%d").date()


def _open_local_read_only(settings: Settings) -> psycopg.Connection[Any]:
    conn = connect(settings, "src")
    # 会话级只读：即使误写 SQL，PG 也会拒绝。
    conn.read_only = True
    return conn


def _table_state(conn: psycopg.Connection[Any], table: str) -> str:
    """返回 ``missing``（迁移未应用）、``empty`` 或 ``rows``。表名是本文件内的常量，不接受外部输入。"""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f'src_wind."{table}"',))
        row = cur.fetchone()
        assert row is not None
        if not row[0]:
            return "missing"
        cur.execute(f'SELECT EXISTS (SELECT 1 FROM "src_wind"."{table}")')
        has = cur.fetchone()
    assert has is not None
    return "rows" if has[0] else "empty"


@pytest.mark.integration
def test_live_citics1_matches_wx2_snapshot_on_every_month_end() -> None:
    settings = get_settings()
    if not plane_configured(settings, "src"):
        pytest.skip("src 平面未配置 PG 连接串")
    expected: dict[str, dict[str, Any]] = _load()["expected"]
    conn = _open_local_read_only(settings)
    try:
        state = _table_state(conn, _TABLE)
        if state == "missing":
            pytest.skip(f'src_wind."{_TABLE}" 未建，迁移 0025 尚未应用')
        if state == "empty":
            pytest.skip(f'src_wind."{_TABLE}" 为空，无法对拍')
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT "OBJECT_ID" FROM "src_wind"."{_TABLE}" WHERE "OBJECT_ID" = ANY(%s)',
                ([row[0] for row in _WX2_ONLY_ROWS],),
            )
            present = [row[0] for row in cur.fetchall()]
        assert not present, f"登记为源端已不提供的行在本地出现，须重新核对: {present}"
        repo = PostgresUniverseRepository(conn)
        failures: list[str] = []
        restored = 0
        for key in sorted(expected):
            dt = _day(key)
            want = expected[key]
            lines: list[str] = []
            try:
                for industry in want["industries"]:
                    members = repo.members_at(
                        as_of=dt,
                        dt=dt,
                        universe_id=f"citics1:{industry}",
                    )
                    lines.extend(f"{industry}|{member.asset_id}" for member in members)
            except (InvalidQueryError, EmptyDomainError) as exc:
                # 区间重叠、空域等报错原样记录，消息里已带日期与代码。
                failures.append(f"{key}: {type(exc).__name__}: {exc}")
                continue
            extra = _wx2_only_lines(key)
            restored += len(extra)
            lines.extend(extra)
            lines.sort()
            digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
            if len(lines) != want["count"] or digest != want["sha256"]:
                failures.append(f"{key}: local {len(lines)} vs wx2 {want['count']}")
    finally:
        conn.close()
    print(f"\n中信一级 {len(expected)} 个月末，补回 wx2 独有行 {restored} 次，失败 {len(failures)}")
    assert not failures, (
        f"中信一级成分不一致 {len(failures)}/{len(expected)} 个月末: "
        f"{failures[:_FAILURE_LIST_LIMIT]}"
    )
