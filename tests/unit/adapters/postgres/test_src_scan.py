"""Wind 镜像到标准日历快照的读取边界。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from quantagent.adapters.postgres.errors import PostgresAdapterError
from quantagent.adapters.postgres.src_scan import scan_trade_cal


@pytest.mark.unit
def test_scan_trade_cal_expands_each_market_independently() -> None:
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [
        {"exchange": "SSE", "trade_day": "20261113"},
        {"exchange": "SSE", "trade_day": "20261116"},
        {"exchange": "SZSE", "trade_day": "20261116"},
    ]

    rows = scan_trade_cal(conn)

    assert 'FROM "src_wind"."ASHARECALENDAR"' in cur.execute.call_args.args[0]
    assert [
        (row["exchange"], row["cal_date"], row["is_open"], row["pretrade_date"]) for row in rows
    ] == [
        ("SSE", "20261113", 1, None),
        ("SSE", "20261114", 0, "20261113"),
        ("SSE", "20261115", 0, "20261113"),
        ("SSE", "20261116", 1, "20261113"),
        ("SZSE", "20261116", 1, None),
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("exchange", "trade_day", "message"),
    [
        (None, "20261113", "交易所为空"),
        ("SSE", None, "日期非法"),
        ("SSE", "20260230", "日期非法"),
        ("SSE", "2026W011", "日期非法"),
        ("SSE", "20261113", "开市日重复"),
    ],
)
def test_scan_trade_cal_rejects_invalid_rows(
    exchange: str | None, trade_day: str | None, message: str
) -> None:
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = [
        {"exchange": "SSE", "trade_day": "20261113"},
        {"exchange": exchange, "trade_day": trade_day},
    ]
    with pytest.raises(PostgresAdapterError, match=message):
        scan_trade_cal(conn)
