"""本地研究库上的 ST 状态与旧仓 wx2 快照的 sha256 对拍，取 2024-01-31。

``src_wind."ASHAREST"`` 为空时跳过。跳过不算通过，只说明本机还没有可对拍的数据。
期望值读自 golden 快照，不在这里重复写死。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from quantagent.adapters.postgres.st import PostgresStStatusRepository
from quantagent.platform.config import get_settings
from quantagent.platform.pg import connect, plane_configured

_FIXTURE = Path(__file__).parents[1] / "golden" / "universe" / "ashare_st_wx2.json"
_DAY = date(2024, 1, 31)


@pytest.mark.integration
def test_live_st_on_2024_01_31_matches_legacy_snapshot() -> None:
    settings = get_settings()
    if not plane_configured(settings, "src"):
        pytest.skip("src 平面未配置 PG 连接串")
    want = json.loads(_FIXTURE.read_text(encoding="utf-8"))["expected"]["20240131"]
    conn = connect(settings, "src")
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM "src_wind"."ASHAREST"')
            row = cur.fetchone()
            assert row is not None
            total = row[0]
        if total == 0:
            pytest.skip('src_wind."ASHAREST" 为空，无法对拍')
        codes = sorted(PostgresStStatusRepository(conn).st_codes_at(as_of=_DAY, dt=_DAY))
    finally:
        conn.close()
    assert len(codes) == want["count"]
    assert hashlib.sha256("\n".join(codes).encode("utf-8")).hexdigest() == want["sha256"]
