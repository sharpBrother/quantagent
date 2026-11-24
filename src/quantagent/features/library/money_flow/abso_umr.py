"""``pf_single_abso_umr_1_mean_pos``。

旧仓 ``guosen_umr.py`` 的 ``ABSO`` 取小单主动买入金额占成交额的负比例：
``-(BUY_VALUE_SMALL_ORDER_ACT / S_DQ_AMOUNT)``。UMR 框架与 ``tr_umr`` 相同：按市场开市日排风险序列，
10 日滚动偏离，乘超额收益（相对 000985.CSI），取最后 60 日半衰期 30 的加权和。消费方向 +1，窗口 1。

缺失与分母为 0 都使风险系数无定义。v2 语义下，窗口内任一所需输入缺失即不产值（见 ``umr_math.weighted_umr``）。
旧仓用 nansum 跳过缺失项，因此 wx2 中有值而本仓无值的股票，要在 golden 中逐行核实窗口内确有缺失输入。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from quantagent.domain.errors import FeatureLookupError
from quantagent.domain.feature_lineage import derive_feature_lineage
from quantagent.features.library.price.tr_umr import (
    BENCHMARK,
    HALF_LIFE,
    RET_WINDOW,
    RISK_WINDOW,
    reject_invalid_tr_umr_inputs,
)
from quantagent.features.library.umr_math import risk_coef, weighted_umr
from quantagent.platform.identity import digest_json

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.index_returns.types import IndexReturn
    from quantagent.domain.money_flow.types import MoneyFlow
    from quantagent.domain.prices.types import DailyPrice

FEATURE_ID = "pf_single_abso_umr_1_mean_pos"
DEFINITION_VERSION = "v1"
LOOKBACK = RET_WINDOW + RISK_WINDOW - 1
MEAN_WINDOW = 1
SIGN = "1"

PARAMS = {
    "risk_window": RISK_WINDOW,
    "ret_window": RET_WINDOW,
    "half_life": HALF_LIFE,
    "benchmark": BENCHMARK,
    "sign": SIGN,
    "mean_window": MEAN_WINDOW,
}
PARAM_HASH = digest_json(PARAMS)


@dataclass(frozen=True)
class AbsoUmrValue:
    event_dt: date
    asset_id: str
    value: float
    knowledge_dt: date
    pit_grade: str


def reject_invalid_abso_umr_inputs(
    open_days: Sequence[date],
    prices: Sequence[DailyPrice],
    money_flows: Sequence[MoneyFlow],
    index_returns: Sequence[IndexReturn],
) -> None:
    """复用 tr_umr 的开市日、行情、指数校验，再查资金流键重复。"""
    reject_invalid_tr_umr_inputs(open_days, prices, index_returns)
    seen: set[tuple[date, str]] = set()
    for flow in money_flows:
        key = (flow.trade_dt, flow.wind_code)
        if key in seen:
            raise FeatureLookupError(f"资金流键重复: {flow.wind_code} {flow.trade_dt.isoformat()}")
        seen.add(key)


def abso_umr_value(
    open_days: Sequence[date],
    prices: Sequence[DailyPrice],
    money_flows: Sequence[MoneyFlow],
    index_returns: Sequence[IndexReturn],
    *,
    price_contract: VisibilityContract,
    money_flow_contract: VisibilityContract,
    index_contract: VisibilityContract,
) -> AbsoUmrValue | None:
    """``open_days`` 是含截面日在内的开市日，长度必须为 69。只接受一只股票的输入。"""
    reject_invalid_abso_umr_inputs(open_days, prices, money_flows, index_returns)
    codes = {row.wind_code for row in prices} | {row.wind_code for row in money_flows}
    if len(codes) > 1:
        raise FeatureLookupError("ABSO_UMR 一次只接受一只股票")
    return abso_umr_from_maps(
        tuple(sorted(open_days)),
        price_by_day={row.trade_dt: row for row in prices},
        flow_by_day={row.trade_dt: row for row in money_flows},
        index_by_day={row.trade_dt: row for row in index_returns},
        asset_id=next(iter(codes), None),
        price_contract=price_contract,
        money_flow_contract=money_flow_contract,
        index_contract=index_contract,
    )


def abso_umr_from_maps(
    ordered_days: Sequence[date],
    *,
    price_by_day: Mapping[date, DailyPrice],
    flow_by_day: Mapping[date, MoneyFlow],
    index_by_day: Mapping[date, IndexReturn],
    asset_id: str | None,
    price_contract: VisibilityContract,
    money_flow_contract: VisibilityContract,
    index_contract: VisibilityContract,
) -> AbsoUmrValue | None:
    """面板批量计算用。调用方已按股票、按日建好映射，已校验过输入。

    ``ordered_days`` 必须升序且长度为 69。
    """
    if len(ordered_days) != LOOKBACK:
        return None
    abso = [_abso(price_by_day.get(day), flow_by_day.get(day)) for day in ordered_days]
    excess = [_excess(price_by_day.get(day), index_by_day.get(day)) for day in ordered_days]
    coef = risk_coef(abso, risk_window=RISK_WINDOW)
    value = weighted_umr(
        coef[-RET_WINDOW:],
        excess[-RET_WINDOW:],
        ret_window=RET_WINDOW,
        half_life=HALF_LIFE,
        sign=float(SIGN),
    )
    if value is None:
        return None
    if asset_id is None:
        raise FeatureLookupError("ABSO_UMR 有值但没有股票输入")
    knowledge_dt, pit_grade = _lineage(
        ordered_days,
        price_by_day=price_by_day,
        flow_by_day=flow_by_day,
        index_by_day=index_by_day,
        price_contract=price_contract,
        money_flow_contract=money_flow_contract,
        index_contract=index_contract,
    )
    return AbsoUmrValue(
        event_dt=ordered_days[-1],
        asset_id=asset_id,
        value=value,
        knowledge_dt=knowledge_dt,
        pit_grade=pit_grade,
    )


def _abso(price: DailyPrice | None, flow: MoneyFlow | None) -> float:
    if price is None or flow is None:
        return math.nan
    buy = flow.buy_value_small_order_act
    amount = price.amount
    if buy is None or amount is None:
        return math.nan
    # 旧仓 _safe_divide 把分母 0 换成 NaN。这里直接判无定义。
    denominator = float(amount)
    if denominator == 0.0:
        return math.nan
    value = -(float(buy) / denominator)
    if not math.isfinite(value):
        return math.nan
    return value


def _excess(price: DailyPrice | None, index_row: IndexReturn | None) -> float:
    # 与 tr_umr 相同：涨跌幅单位是百分数点，直接相减，不除以 100。
    if price is None or index_row is None:
        return math.nan
    stock = price.pct_change
    benchmark = index_row.pct_change
    if stock is None or benchmark is None:
        return math.nan
    value = float(stock) - float(benchmark)
    if not math.isfinite(value):
        return math.nan
    return value


def _lineage(
    ordered_days: Sequence[date],
    *,
    price_by_day: Mapping[date, DailyPrice],
    flow_by_day: Mapping[date, MoneyFlow],
    index_by_day: Mapping[date, IndexReturn],
    price_contract: VisibilityContract,
    money_flow_contract: VisibilityContract,
    index_contract: VisibilityContract,
) -> tuple[date, str]:
    # 血缘取窗口内实际读到的每一行。缺失的日子没有行，不进入血缘。
    inputs: list[tuple[date, str]] = []
    for day in ordered_days:
        if day in price_by_day:
            inputs.append((day, price_contract.visibility.grade))
        if day in flow_by_day:
            inputs.append((day, money_flow_contract.visibility.grade))
        if day in index_by_day:
            inputs.append((day, index_contract.visibility.grade))
    return derive_feature_lineage(tuple(inputs))
