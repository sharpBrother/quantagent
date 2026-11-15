"""切段振幅与 wx2.stock_cutamp 在 6 位小数上一致。"""

from __future__ import annotations

import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from quantagent.domain.prices.types import DailyPrice

from quantagent.adapters.postgres.daily_prices import (
    PostgresDailyPriceRepository,
    load_price_visibility,
)
from quantagent.features.library.price.cutamp import WINDOW, cutamp_value
from quantagent.platform.config import get_settings
from quantagent.platform.pg import connect

_FIXTURE = Path(__file__).parents[1] / "golden" / "market_data" / "cutamp_wx2.json"
_SCALE = Decimal("0.000001")


@pytest.mark.integration
def test_cutamp_matches_wx2_stored_scale() -> None:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    expected = payload["rows"]
    codes = ("000001.SZ", "600000.SH")
    conn = connect(get_settings(), "src")
    try:
        prices = PostgresDailyPriceRepository(conn).list_prices(
            as_of=date(2024, 1, 5),
            start=date(2023, 11, 1),
            end=date(2024, 1, 5),
            wind_codes=codes,
        )
    finally:
        conn.close()
    by_code: dict[str, list[DailyPrice]] = {code: [] for code in codes}
    for row in prices:
        by_code[row.wind_code].append(row)
    contract = load_price_visibility()
    for item in expected:
        day = date.fromisoformat(item["trade_dt"])
        series = [row for row in by_code[item["wind_code"]] if row.trade_dt <= day]
        result = cutamp_value(series[-WINDOW:], contract=contract)
        assert result is not None
        assert result.event_dt == day
        assert result.knowledge_dt == day
        assert result.pit_grade == "A"
        assert result.value == -result.raw
        stored = result.raw.quantize(_SCALE, rounding=ROUND_HALF_UP)
        assert stored == Decimal(item["cutamp"])
