"""``pf_single_actlargemedcut_1_mean_pos``。

旧仓 ``factors/factors.py`` 的 ``ACTLARGEMEDCUT``（第 135–156 行）：主动大中单强度，按收益率切割。
每日 ``act = (大单买 - 大单卖 + 中单买 - 中单卖) / (四项之和)``。窗口内按 ``ratio``（复权收盘涨跌幅，
``100 * (S_DQ_ADJCLOSE / S_DQ_ADJPRECLOSE - 1)``）降序排序，取前 15% 的 act 均值。消费方向 +1，窗口 1。

窗口是个股自有的最近 20 行行情（旧仓 ``tail(20)``）。
排序并列：旧仓 ``sort_values('ratio', ascending=False)`` 是 quicksort，并列行谁进前 15% 由算法决定，
这里用 ``legacy_descending_order`` 复现。``ratio`` 用精确十进制算，并列判断与旧仓 SQL 的精确并列一致。

缺失与无定义：窗口内任一行缺任一输入，或某日 act 的分母为 0，都不产值。
旧仓 ``dropna()`` 会删掉缺失行后再切割，窗口实际变短。本仓采用严格口径，依据见 docs/adr/2026-11-24-moneyflow-factors-batch-2a.md（调度方建议，未经负责人裁定）。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import TYPE_CHECKING

from quantagent.domain.feature_lineage import derive_feature_lineage
from quantagent.features.library._legacy_sort import legacy_descending_order
from quantagent.platform.identity import digest_json

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.money_flow.types import MoneyFlow
    from quantagent.domain.prices.types import DailyPrice

FEATURE_ID = "pf_single_actlargemedcut_1_mean_pos"
DEFINITION_VERSION = "v1"
WINDOW = 20
CUT_RATIO = Decimal("0.15")
SIGN = Decimal("1")

PARAMS = {
    "window": WINDOW,
    "cut_ratio": format(CUT_RATIO, "f"),
    "sign": format(SIGN, "f"),
    "mean_window": 1,
}
PARAM_HASH = digest_json(PARAMS)

# 比率用的十进制精度。旧仓 SQL 的除法结果截断到约 18 位小数，远细于并列判断需要的精度；
# 这里取 50 位，使相等的比率在十进制上严格相等，不相等的比率也不会在转成 float 时合并。
_RATIO_PRECISION = 50


@dataclass(frozen=True)
class ActLargeMedCutValue:
    event_dt: date
    asset_id: str
    raw: Decimal
    value: Decimal
    knowledge_dt: date
    pit_grade: str


def _daily_terms(row: DailyPrice, flow: MoneyFlow | None) -> tuple[Decimal, Decimal] | None:
    """返回 (当日 act, 当日 ratio)。任一输入缺失，或 act 与 ratio 的分母为 0，则无定义。"""
    if flow is None or row.adj_close is None or row.adj_preclose is None:
        return None
    if row.adj_preclose == 0:
        return None
    big_buy = flow.buy_value_large_order_act
    big_sell = flow.sell_value_large_order_act
    med_buy = flow.buy_value_med_order_act
    med_sell = flow.sell_value_med_order_act
    if big_buy is None or big_sell is None or med_buy is None or med_sell is None:
        return None
    total = big_buy + big_sell + med_buy + med_sell
    if total == 0:
        return None
    act = (big_buy - big_sell + med_buy - med_sell) / total
    with localcontext() as ctx:
        ctx.prec = _RATIO_PRECISION
        ratio = Decimal(100) * (row.adj_close / row.adj_preclose - 1)
    return act, ratio


def actlargemedcut_value(
    window: Sequence[DailyPrice],
    flows: Mapping[date, MoneyFlow],
    *,
    price_contract: VisibilityContract,
    money_flow_contract: VisibilityContract,
) -> ActLargeMedCutValue | None:
    """``window`` 是个股自有的最近 20 行行情，最后一行是截面日，按交易日升序。"""
    if len(window) != WINDOW:
        return None
    rows = tuple(window)
    acts: list[Decimal] = []
    ratios: list[Decimal] = []
    for row in rows:
        terms = _daily_terms(row, flows.get(row.trade_dt))
        if terms is None:
            return None
        acts.append(terms[0])
        ratios.append(terms[1])
    # 按 ratio 降序的下标。并列的先后与旧仓 pandas quicksort 一致。
    order = legacy_descending_order([float(ratio) for ratio in ratios])
    cut = int(CUT_RATIO * len(order))
    if cut == 0:
        return None
    raw = sum((acts[i] for i in order[:cut]), Decimal(0)) / cut
    grade = price_contract.visibility.grade
    flow_grade = money_flow_contract.visibility.grade
    inputs = [(row.trade_dt, grade) for row in rows]
    inputs.extend((row.trade_dt, flow_grade) for row in rows)
    knowledge_dt, pit_grade = derive_feature_lineage(tuple(inputs))
    return ActLargeMedCutValue(
        event_dt=rows[-1].trade_dt,
        asset_id=rows[-1].wind_code,
        raw=raw,
        value=SIGN * raw,
        knowledge_dt=knowledge_dt,
        pit_grade=pit_grade,
    )
