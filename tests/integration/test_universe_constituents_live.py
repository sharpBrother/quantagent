"""本地研究库上的 000300.SH 成分与旧仓 wx2 快照的 sha256 对拍。
``src_wind.AINDEXMEMBERS`` 为空，或 2024-01-31 无该指数成分行时跳过。跳过不算通过，
只说明本机还没有可对拍的数据。
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import TYPE_CHECKING

import pytest

from quantagent.adapters.postgres.universe import PostgresUniverseRepository
from quantagent.platform.config import get_settings
from quantagent.platform.pg import connect, plane_configured

if TYPE_CHECKING:
    from quantagent.domain.universe import UniverseMember

_UNIVERSE_ID = "index:000300.SH"
_DAY = date(2024, 1, 31)
_EXPECTED_COUNT = 300
_EXPECTED_SHA256 = "5d3c6b8b603a42def5f3eddce7a18df91fa97acd348e7778415c3fb186920531"


@pytest.mark.integration
def test_live_hs300_matches_legacy_snapshot_on_2024_01_31() -> None:
    settings = get_settings()
    if not plane_configured(settings, "src"):
        pytest.skip("src 平面未配置 PG 连接串")
    conn = connect(settings, "src")
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT count(*) FROM "src_wind"."AINDEXMEMBERS" WHERE "S_INFO_WINDCODE" = %s',
                ("000300.SH",),
            )
            member_rows = _scalar(cur.fetchone())
        if member_rows == 0:
            pytest.skip('src_wind."AINDEXMEMBERS" 中无 000300.SH 成分行，无法对拍')
        members: tuple[UniverseMember, ...] = PostgresUniverseRepository(conn).members_at(
            as_of=_DAY,
            dt=_DAY,
            universe_id=_UNIVERSE_ID,
        )
    finally:
        conn.close()
    codes = [member.asset_id for member in members]
    assert len(codes) == _EXPECTED_COUNT
    assert hashlib.sha256("\n".join(codes).encode("utf-8")).hexdigest() == _EXPECTED_SHA256


def _scalar(row: object) -> int:
    assert isinstance(row, tuple)
    value = row[0]
    assert isinstance(value, int)
    return value
