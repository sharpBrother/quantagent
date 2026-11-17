"""本地研究库上的 all_a 成员与旧仓 wx2 快照的 sha256 对拍。

源表为空，或目标日衍生指标无行时跳过。跳过不算通过，只说明本机还没有可对拍的数据。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from quantagent.adapters.postgres.universe import PostgresUniverseRepository
from quantagent.platform.config import get_settings
from quantagent.platform.pg import connect, plane_configured

_SNAPSHOT = Path(__file__).parents[1] / "golden" / "universe" / "all_a_wx2.json"
_DAY = date(2024, 1, 5)
_DAY_KEY = "20240105"


@pytest.mark.integration
def test_live_all_a_matches_legacy_snapshot_on_2024_01_05() -> None:
    settings = get_settings()
    if not plane_configured(settings, "src"):
        pytest.skip("src 平面未配置 PG 连接串")
    expected = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))["dates"][_DAY_KEY]

    conn = connect(settings, "src")
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM "src_wind"."ASHAREDESCRIPTION"')
            description_rows = _scalar(cur.fetchone())
            cur.execute(
                'SELECT count(*) FROM "src_wind"."ASHAREEODDERIVATIVEINDICATOR" '
                'WHERE "TRADE_DT" = %s',
                (_DAY_KEY,),
            )
            indicator_rows = _scalar(cur.fetchone())
        if description_rows == 0:
            pytest.skip("src_wind.ASHAREDESCRIPTION 为空，无法计算规则池")
        if indicator_rows == 0:
            pytest.skip(
                f"src_wind.ASHAREEODDERIVATIVEINDICATOR 在 {_DAY_KEY} 无行，无法判断市值观测"
            )
        members = PostgresUniverseRepository(conn).members_at(
            as_of=_DAY,
            dt=_DAY,
            universe_id="all_a",
        )
    finally:
        conn.close()

    codes = [member.asset_id for member in members]
    assert len(codes) == expected["count"]
    assert hashlib.sha256("\n".join(codes).encode("utf-8")).hexdigest() == expected["sha256"]


def _scalar(row: object) -> int:
    assert isinstance(row, tuple)
    value = row[0]
    assert isinstance(value, int)
    return value
