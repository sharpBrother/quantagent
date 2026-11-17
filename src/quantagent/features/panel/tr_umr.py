"""把真实波幅 UMR 收成因子长表行。不写文件，也不接受手填可见日。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.domain.feature_value import FeatureValue
from quantagent.features.library.price.tr_umr import (
    DEFINITION_VERSION,
    FEATURE_ID,
    LOOKBACK,
    PARAM_HASH,
    reject_invalid_tr_umr_inputs,
    tr_umr_value,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date, datetime

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.index_returns.types import IndexReturn
    from quantagent.domain.prices.types import DailyPrice


def build_tr_umr_values(
    prices: Sequence[DailyPrice],
    index_returns: Sequence[IndexReturn],
    open_days: Sequence[date],
    *,
    price_contract: VisibilityContract,
    index_contract: VisibilityContract,
    start: date,
    end: date,
    computed_at: datetime,
    run_id: str,
) -> tuple[FeatureValue, ...]:
    """只产 ``[start, end]`` 内的开市日。窗口不足或值无定义时不产行。

    截面日必须在开市日序列里。窗口按这些开市日往前数，不按股票自己的打印补齐。
    """
    reject_invalid_tr_umr_inputs(open_days, prices, index_returns)
    by_code: dict[str, list[DailyPrice]] = {}
    for row in prices:
        by_code.setdefault(row.wind_code, []).append(row)
    opens = tuple(sorted(open_days))
    values: list[FeatureValue] = []
    for code in sorted(by_code):
        series = tuple(by_code[code])
        for index, event_dt in enumerate(opens):
            if event_dt < start or event_dt > end or index < LOOKBACK - 1:
                continue
            window = opens[index - (LOOKBACK - 1) : index + 1]
            computed = tr_umr_value(
                window,
                series,
                index_returns,
                price_contract=price_contract,
                index_contract=index_contract,
            )
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
