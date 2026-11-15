"""本机 Wind 镜像与 golden 样本一致。wx2 不在这条路径上。"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from quantagent.adapters.postgres.daily_prices import PostgresDailyPriceRepository
from quantagent.platform.config import get_settings
from quantagent.platform.pg import connect

_FIXTURE = (
    Path(__file__).parents[1] / "golden" / "market_data" / "get_daily_prices_wind_mirror.json"
)


@pytest.mark.integration
def test_live_mirror_matches_captured_slice() -> None:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    expected = payload["rows"]
    conn = connect(get_settings(), "src")
    try:
        rows = PostgresDailyPriceRepository(conn).list_prices(
            as_of=date(2024, 1, 5),
            start=date(2024, 1, 2),
            end=date(2024, 1, 5),
            wind_codes=("000001.SZ", "600000.SH", "999999.SZ"),
        )
    finally:
        conn.close()
    actual = [
        {
            "trade_dt": row.trade_dt.isoformat(),
            "wind_code": row.wind_code,
            "open": format(row.open, "f") if row.open is not None else None,
            "high": format(row.high, "f") if row.high is not None else None,
            "low": format(row.low, "f") if row.low is not None else None,
            "close": format(row.close, "f") if row.close is not None else None,
            "volume": format(row.volume, "f") if row.volume is not None else None,
            "amount": format(row.amount, "f") if row.amount is not None else None,
            "pct_change": format(row.pct_change, "f") if row.pct_change is not None else None,
        }
        for row in rows
    ]
    assert actual == expected
    assert rows[0].close == Decimal("9.2100")
