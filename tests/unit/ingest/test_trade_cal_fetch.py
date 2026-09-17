"""Tushare trade_cal 原生字段规范化。不打真实 API。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantagent.ingest.errors import EmptyPayloadError, SourceFetchError
from quantagent.ingest.sources.tushare.trade_cal import fetch_trade_cal, normalize_trade_cal_frame


class _FakeClient:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames
        self.calls: list[tuple[str, str, str]] = []

    def trade_cal(self, *, exchange: str, start_date: str, end_date: str) -> pd.DataFrame:
        self.calls.append((exchange, start_date, end_date))
        return self.frames[exchange]


@pytest.mark.unit
def test_normalize_keeps_native_yyyymmdd_and_int_is_open() -> None:
    frame = pd.DataFrame(
        {
            "exchange": ["SSE"],
            "cal_date": ["2026-01-05"],
            "is_open": [np.int64(1)],
            "pretrade_date": [np.nan],
        }
    )
    rows = normalize_trade_cal_frame(frame, requested_exchange="SSE")
    assert rows == [
        {
            "exchange": "SSE",
            "cal_date": "20260105",
            "is_open": 1,
            "pretrade_date": None,
        }
    ]


@pytest.mark.unit
def test_fetch_sorts_and_rejects_empty() -> None:
    client = _FakeClient(
        {
            "SZSE": pd.DataFrame(
                {
                    "exchange": ["SZSE"],
                    "cal_date": ["20260106"],
                    "is_open": [0],
                    "pretrade_date": ["20260105"],
                }
            ),
            "SSE": pd.DataFrame(
                {
                    "exchange": ["SSE"],
                    "cal_date": ["20260106"],
                    "is_open": [0],
                    "pretrade_date": ["20260105"],
                }
            ),
        }
    )
    rows = fetch_trade_cal(
        client,
        start_date="20260101",
        end_date="20260131",
        exchanges=("SZSE", "SSE"),
    )
    assert [row["exchange"] for row in rows] == ["SSE", "SZSE"]
    empty = _FakeClient(
        {
            "SSE": pd.DataFrame(columns=["exchange", "cal_date", "is_open", "pretrade_date"]),
            "SZSE": pd.DataFrame(columns=["exchange", "cal_date", "is_open", "pretrade_date"]),
        }
    )
    with pytest.raises(EmptyPayloadError):
        fetch_trade_cal(empty, start_date="20260101", end_date="20260131")


@pytest.mark.unit
def test_is_open_out_of_range_fail_closed() -> None:
    frame = pd.DataFrame(
        {
            "exchange": ["SSE"],
            "cal_date": ["20260105"],
            "is_open": [2],
            "pretrade_date": [None],
        }
    )
    with pytest.raises(SourceFetchError, match="is_open"):
        normalize_trade_cal_frame(frame, requested_exchange="SSE")
