"""把 MIF 的个股窗口收成因子长表行。不写文件，也不接受手填可见日。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.domain.errors import DerivativeIndicatorLookupError
from quantagent.domain.feature_value import FeatureValue
from quantagent.features.library.price.mif import (
    DEFINITION_VERSION,
    FEATURE_ID,
    LAG,
    PARAM_HASH,
    WINDOW,
    mif_value,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date, datetime

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.derivative_indicator.types import Turnover
    from quantagent.domain.prices.types import DailyPrice


def build_mif_values(
    prices: Sequence[DailyPrice],
    turnovers: Sequence[Turnover],
    *,
    price_contract: VisibilityContract,
    turnover_contract: VisibilityContract,
    start: date,
    end: date,
    computed_at: datetime,
    run_id: str,
) -> tuple[FeatureValue, ...]:
    """截面只来自价格行：每个价格行都是一个候选截面，衍生指标里没有对应价格行的日期（非交易日行）
    不会被查到，等于被丢弃。窗口按个股自有行往前数 ``WINDOW + LAG`` 行，不足则不产行。
    """
    by_code: dict[str, list[DailyPrice]] = {}
    for row in prices:
        by_code.setdefault(row.wind_code, []).append(row)
    turnover_by_code: dict[str, dict[date, Turnover]] = {}
    for item in turnovers:
        bucket = turnover_by_code.setdefault(item.wind_code, {})
        if item.trade_dt in bucket:
            raise DerivativeIndicatorLookupError(
                f"衍生指标键重复: {item.wind_code} {item.trade_dt.isoformat()}"
            )
        bucket[item.trade_dt] = item
    span = WINDOW + LAG
    values: list[FeatureValue] = []
    for code in sorted(by_code):
        series = sorted(by_code[code], key=lambda row: row.trade_dt)
        turnover_by_day = turnover_by_code.get(code, {})
        # 用下标直接取窗口，与 last_n_trading_days 的语义一致（序列已按交易日升序、无重复日）。
        # 逐行调用 last_n_trading_days 会每次全扫个股序列，全 A 股时是 O(n²)。
        for index in range(span - 1, len(series)):
            event = series[index]
            if event.trade_dt < start or event.trade_dt > end:
                continue
            computed = mif_value(
                series[index - (span - 1) : index + 1],
                turnover_by_day,
                price_contract=price_contract,
                turnover_contract=turnover_contract,
            )
            if computed is None:
                continue
            values.append(
                FeatureValue(
                    event_dt=computed.event_dt,
                    asset_id=computed.asset_id,
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
