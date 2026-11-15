"""切段振幅长表：可见日来自输入，既有文件不覆盖。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from quantagent.adapters.lake.feature_value import LakeFeatureRepository
from quantagent.adapters.postgres.daily_prices import load_price_visibility
from quantagent.domain.errors import EmptyDomainError
from quantagent.domain.prices.types import DailyPrice
from quantagent.features.library.price.cutamp import FEATURE_ID, PARAM_HASH, WINDOW
from quantagent.features.panel.cutamp import build_cutamp_values
from quantagent.lake.materialize.feature_value import write_feature_values
from quantagent.lake.partitions.layout import LakeLayoutError

if TYPE_CHECKING:
    from pathlib import Path


def _prices() -> tuple[DailyPrice, ...]:
    start = date(2024, 1, 1)
    return tuple(
        DailyPrice(
            trade_dt=start + timedelta(days=index),
            wind_code="000001.SZ",
            open=Decimal("10"),
            high=Decimal(10 + index),
            low=Decimal("10"),
            close=Decimal("10"),
            volume=Decimal("1"),
            amount=Decimal("1"),
            pct_change=Decimal("0"),
            limit_up=Decimal("11"),
            limit_down=Decimal("9"),
            adj_close=Decimal(index + 1),
        )
        for index in range(WINDOW)
    )


@pytest.mark.unit
def test_cutamp_rows_keep_derived_visibility_and_refuse_overwrite(tmp_path: Path) -> None:
    rows = build_cutamp_values(
        _prices(),
        contract=load_price_visibility(),
        start=date(2024, 1, 20),
        end=date(2024, 1, 20),
        computed_at=datetime(2024, 1, 20, tzinfo=UTC).replace(tzinfo=None),
        run_id="run-test",
    )
    assert len(rows) == 1
    assert rows[0].feature_id == FEATURE_ID
    assert rows[0].param_hash == PARAM_HASH
    assert rows[0].knowledge_dt == rows[0].event_dt
    assert rows[0].pit_grade == "A"
    assert rows[0].value < 0

    dest = tmp_path / "feature" / "value"
    write_feature_values(rows, dest)
    visible = LakeFeatureRepository(dest).scan_window(
        as_of=rows[0].event_dt,
        feature_id=FEATURE_ID,
        definition_version=rows[0].definition_version,
        param_hash=PARAM_HASH,
        start=rows[0].event_dt,
        end=rows[0].event_dt,
    )
    assert len(visible) == 1
    assert visible[0].knowledge_dt == rows[0].knowledge_dt
    with pytest.raises(EmptyDomainError):
        LakeFeatureRepository(dest).scan_window(
            as_of=rows[0].event_dt - timedelta(days=1),
            feature_id=FEATURE_ID,
            definition_version=rows[0].definition_version,
            param_hash=PARAM_HASH,
            start=rows[0].event_dt,
            end=rows[0].event_dt,
        )
    with pytest.raises(LakeLayoutError, match="拒绝覆盖"):
        write_feature_values(rows, dest)
