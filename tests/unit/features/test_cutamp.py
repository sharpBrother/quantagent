"""切段振幅：窗口不足是缺失，血缘不能手填。"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.errors import FeatureLookupError
from quantagent.domain.feature_lineage import derive_feature_lineage
from quantagent.domain.prices.types import DailyPrice
from quantagent.features.library.price.cutamp import WINDOW, cutamp_value


def _contract(grade: str = "A") -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": "src.wind.ashareeodprices",
            "doc_ref": "docs/contracts/src-wind-ashareeodprices.md",
            "temporal_kind": "point_event",
            "event_field": "TRADE_DT",
            "visibility": {
                "rule": "same_day_close",
                "grade": grade,
                "rationale": "切段振幅测试用的行情可见性规则说明足够长",
            },
            "pit_recoverable": True,
        }
    )


def _price(
    day: date, *, close: str = "10", high: str = "11", low: str = "10", adj: str = "10"
) -> DailyPrice:
    return DailyPrice(
        trade_dt=day,
        wind_code="000001.SZ",
        open=Decimal("10"),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1"),
        amount=Decimal("1"),
        pct_change=Decimal("0"),
        limit_up=Decimal("11"),
        limit_down=Decimal("9"),
        adj_close=Decimal(adj),
    )


@pytest.mark.unit
def test_short_window_is_missing() -> None:
    start = date(2024, 1, 1)
    rows = tuple(_price(start + timedelta(days=i), adj=str(i)) for i in range(WINDOW - 1))
    assert cutamp_value(rows, contract=_contract()) is None


@pytest.mark.unit
def test_lineage_uses_latest_input_and_worst_grade() -> None:
    knowledge_dt, grade = derive_feature_lineage(((date(2024, 1, 2), "A"), (date(2024, 1, 5), "D")))
    assert knowledge_dt == date(2024, 1, 5)
    assert grade == "D"
    with pytest.raises(FeatureLookupError, match="不允许把 knowledge_dt 提前"):
        derive_feature_lineage(((date(2024, 1, 2), "A"),), extra_lag_days=-1)


@pytest.mark.unit
def test_equal_adj_close_keeps_trade_date_order() -> None:
    start = date(2024, 1, 1)
    rows = []
    for index in range(WINDOW):
        # 前两日复权收盘价相同，振幅不同；输入顺序故意颠倒。
        if index == 0:
            high, adj, day = "20", "1", start + timedelta(days=1)
        elif index == 1:
            high, adj, day = "11", "1", start
        else:
            high, adj, day = "10", str(index + 1), start + timedelta(days=index)
        rows.append(_price(day, high=high, low="10", adj=adj))
    forward = cutamp_value(tuple(rows), contract=_contract())
    backward = cutamp_value(tuple(reversed(rows)), contract=_contract())
    assert forward is not None and backward is not None
    assert forward.raw == backward.raw


@pytest.mark.unit
def test_value_is_negative_raw_and_grade_follows_input() -> None:
    start = date(2024, 1, 1)
    rows = tuple(
        _price(start + timedelta(days=i), high=str(10 + (i % 3)), low="10", adj=str(i))
        for i in range(WINDOW)
    )
    result = cutamp_value(rows, contract=_contract("D"))
    assert result is not None
    assert result.value == Decimal("-1") * result.raw
    assert result.knowledge_dt == rows[-1].trade_dt
    assert result.pit_grade == "D"
    assert result.event_dt == rows[-1].trade_dt
