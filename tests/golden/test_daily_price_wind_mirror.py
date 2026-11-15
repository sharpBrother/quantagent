"""同一小样本上，Wind 镜像与 wx2 的数值一致。实现差异另记。"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from quantagent.adapters.memory.prices import MemoryDailyPriceRepository
from quantagent.adapters.postgres.daily_prices import load_price_visibility
from quantagent.domain.prices.types import DailyPrice

_FIXTURE = Path(__file__).parent / "market_data" / "get_daily_prices_wind_mirror.json"


def _payload() -> dict[str, object]:
    loaded = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _rows(payload: dict[str, object]) -> tuple[DailyPrice, ...]:
    raw_rows = payload["rows"]
    assert isinstance(raw_rows, list)
    parsed: list[DailyPrice] = []
    for item in raw_rows:
        assert isinstance(item, dict)
        parsed.append(
            DailyPrice(
                trade_dt=date.fromisoformat(str(item["trade_dt"])),
                wind_code=str(item["wind_code"]),
                open=Decimal(str(item["open"])),
                high=Decimal(str(item["high"])),
                low=Decimal(str(item["low"])),
                close=Decimal(str(item["close"])),
                volume=Decimal(str(item["volume"])),
                amount=Decimal(str(item["amount"])),
                pct_change=Decimal(str(item["pct_change"])),
            )
        )
    return tuple(parsed)


@pytest.mark.golden
def test_wind_mirror_slice_keeps_old_behavior_separate() -> None:
    payload = _payload()
    provenance = payload["provenance"]
    old = payload["old_behavior"]
    assert isinstance(provenance, dict)
    assert isinstance(old, dict)
    assert provenance["role"] == "wind_db mirror slice"
    assert provenance["old_source_table"] == "wx2.dbo.ASHAREEODPRICES"
    comparison = payload["comparison"]
    assert isinstance(comparison, dict)
    assert comparison["value_diffs"] == []
    assert comparison["only_wx2"] == []
    assert comparison["only_wind"] == []
    assert payload["wx2_rows"] == payload["rows"]
    assert old["has_as_of"] is False
    assert old["missing_code"] == "no row and no fill"
    rows = _rows(payload)
    assert len(rows) == 8
    assert {row.wind_code for row in rows} == {"000001.SZ", "600000.SH"}
    assert rows[0].trade_dt == date(2024, 1, 2)
    assert rows[-1].trade_dt == date(2024, 1, 5)
    assert "999999.SZ" not in {row.wind_code for row in rows}

    visible = MemoryDailyPriceRepository(rows, contract=load_price_visibility()).list_prices(
        as_of=date(2024, 1, 3),
        start=date(2024, 1, 2),
        end=date(2024, 1, 5),
        wind_codes=("000001.SZ", "600000.SH", "999999.SZ"),
    )
    assert [(row.trade_dt, row.wind_code) for row in visible] == [
        (date(2024, 1, 2), "000001.SZ"),
        (date(2024, 1, 2), "600000.SH"),
        (date(2024, 1, 3), "000001.SZ"),
        (date(2024, 1, 3), "600000.SH"),
    ]
    assert visible[0].close == Decimal("9.2100")
