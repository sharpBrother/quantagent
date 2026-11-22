from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from quantagent.ingest.errors import SourceFetchError
from quantagent.ingest.sources.eastmoney_minute import fetch_day, list_stocks


def response(row: str, market: int = 0) -> SimpleNamespace:
    payload = {"data": {"code": "000001", "market": market, "trends": [row]}}
    return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)


def test_maps_open_high_low_close_without_float_rounding(monkeypatch: pytest.MonkeyPatch) -> None:
    row = "2026-11-20 09:31,11.97,11.97,12.02,11.96,31212,37402763.00,11.985"
    monkeypatch.setattr(
        "quantagent.ingest.sources.eastmoney_minute.get_with_retry", lambda *a, **kw: response(row)
    )
    result = fetch_day("000001.SZ", trade_date=date(2026, 11, 20))
    assert result == [
        (
            "000001.SZ",
            datetime(2026, 11, 20, 9, 31),
            Decimal("11.97"),
            Decimal("12.02"),
            Decimal("11.96"),
            Decimal("11.97"),
            Decimal("31212"),
            Decimal("37402763.00"),
        )
    ]


@pytest.mark.parametrize(
    "row,market",
    [
        ("2026-11-19 09:31,11,11,11,11,1,100,11", 0),
        ("2026-11-20 09:31,11,11,11,11,1,100,11", 1),
        ("2026-11-20 09:31,11,-,11,11,1,100,11", 0),
    ],
)
def test_rejects_wrong_date_market_or_invalid_number(
    monkeypatch: pytest.MonkeyPatch, row: str, market: int
) -> None:
    monkeypatch.setattr(
        "quantagent.ingest.sources.eastmoney_minute.get_with_retry",
        lambda *a, **kw: response(row, market=market),
    )
    with pytest.raises(SourceFetchError):
        fetch_day("000001.SZ", trade_date=date(2026, 11, 20))


def test_stock_list_includes_all_markets_and_checks_paging(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "data": {
            "total": 3,
            "diff": [
                {"f12": "000001", "f13": 0},
                {"f12": "600000", "f13": 1},
                {"f12": "920001", "f13": 0},
            ],
        }
    }
    monkeypatch.setattr(
        "quantagent.ingest.sources.eastmoney_minute.get_with_retry",
        lambda *a, **kw: SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload),
    )
    assert list_stocks() == ("000001.SZ", "600000.SH", "920001.BJ")


def test_stock_list_rejects_duplicate_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "data": {
            "total": 2,
            "diff": [
                {"f12": "000001", "f13": 0},
                {"f12": "000001", "f13": 0},
            ],
        }
    }
    monkeypatch.setattr(
        "quantagent.ingest.sources.eastmoney_minute.get_with_retry",
        lambda *a, **kw: SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload),
    )
    with pytest.raises(SourceFetchError):
        list_stocks()
