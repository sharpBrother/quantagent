"""把切段振幅窗口收成因子长表行。不写文件，也不接受手填可见日。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.domain.feature_value import FeatureValue
from quantagent.features.library.price.cutamp import (
    DEFINITION_VERSION,
    FEATURE_ID,
    PARAM_HASH,
    WINDOW,
    cutamp_value,
)
from quantagent.features.window import last_n_trading_days

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date, datetime

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.prices.types import DailyPrice


def build_cutamp_values(
    prices: Sequence[DailyPrice],
    *,
    contract: VisibilityContract,
    start: date,
    end: date,
    computed_at: datetime,
    run_id: str,
) -> tuple[FeatureValue, ...]:
    """每个代码按交易日滑动 20 日窗口。窗口不足或振幅无定义时不产行。"""
    by_code: dict[str, list[DailyPrice]] = {}
    for row in prices:
        by_code.setdefault(row.wind_code, []).append(row)
    values: list[FeatureValue] = []
    for code in sorted(by_code):
        series = by_code[code]
        for row in series:
            event_dt = row.trade_dt
            if event_dt < start or event_dt > end:
                continue
            window = last_n_trading_days(
                series,
                event_dt=event_dt,
                count=WINDOW,
                trade_dt=lambda item: item.trade_dt,
            )
            if window is None:
                continue
            computed = cutamp_value(window, contract=contract)
            if computed is None:
                continue
            values.append(
                FeatureValue(
                    event_dt=computed.event_dt,
                    asset_id=code,
                    asset_class="stock",
                    feature_id=FEATURE_ID,
                    definition_version=DEFINITION_VERSION,
                    param_hash=PARAM_HASH,
                    value=float(computed.value),
                    knowledge_dt=computed.knowledge_dt,
                    pit_grade=computed.pit_grade,
                    computed_at=computed_at,
                    run_id=run_id,
                )
            )
    return tuple(values)
