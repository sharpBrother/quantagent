"""``pf_single_moneyflowh_1_mean_neg``。

旧仓 ``factors/factors.py`` 的 ``MONEYFLOWH``（第 87–118 行）：窗口内四类量差 VALUE_DIFF 的绝对值之和，
取 ``(机构 + 散户) / (机构 + 大户 + 中户 + 散户)``。Current-20 消费方向为 -1，所以长表存 ``-raw``。

窗口是个股自有的最近 20 行行情（旧仓 ``get_stock_data`` 的 ``tail(20)``），不是开市日。
窗口内任一行缺少任一量差，或四类量差绝对值之和为 0，都不产值。旧仓 pandas ``sum()`` 跳过缺失项，
等于把缺失当 0 计入。本仓采用严格口径，依据见 docs/adr/2026-11-24-moneyflow-factors-batch-2a.md（调度方建议，未经负责人裁定）。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from quantagent.domain.feature_lineage import derive_feature_lineage
from quantagent.platform.identity import digest_json

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.money_flow.types import MoneyFlow
    from quantagent.domain.prices.types import DailyPrice

FEATURE_ID = "pf_single_moneyflowh_1_mean_neg"
DEFINITION_VERSION = "v1"
WINDOW = 20
SIGN = Decimal("-1")

PARAMS = {
    "window": WINDOW,
    "sign": format(SIGN, "f"),
    "mean_window": 1,
}
PARAM_HASH = digest_json(PARAMS)


@dataclass(frozen=True)
class MoneyFlowhValue:
    event_dt: date
    asset_id: str
    raw: Decimal
    value: Decimal
    knowledge_dt: date
    pit_grade: str


def moneyflowh_value(
    window: Sequence[DailyPrice],
    flows: Mapping[date, MoneyFlow],
    *,
    price_contract: VisibilityContract,
    money_flow_contract: VisibilityContract,
) -> MoneyFlowhValue | None:
    """``window`` 是个股自有的最近 20 行行情，最后一行是截面日，按交易日升序。"""
    if len(window) != WINDOW:
        return None
    rows = tuple(window)
    inst = Decimal(0)
    large = Decimal(0)
    med = Decimal(0)
    small = Decimal(0)
    for row in rows:
        flow = flows.get(row.trade_dt)
        if flow is None:
            return None
        institute = flow.value_diff_institute
        large_value = flow.value_diff_large_trader
        med_value = flow.value_diff_med_trader
        small_value = flow.value_diff_small_trader
        if institute is None or large_value is None or med_value is None or small_value is None:
            return None
        inst += abs(institute)
        large += abs(large_value)
        med += abs(med_value)
        small += abs(small_value)
    denominator = inst + large + med + small
    if denominator == 0:
        return None
    raw = (inst + small) / denominator
    grade = price_contract.visibility.grade
    flow_grade = money_flow_contract.visibility.grade
    inputs = [(row.trade_dt, grade) for row in rows]
    inputs.extend((row.trade_dt, flow_grade) for row in rows)
    knowledge_dt, pit_grade = derive_feature_lineage(tuple(inputs))
    return MoneyFlowhValue(
        event_dt=rows[-1].trade_dt,
        asset_id=rows[-1].wind_code,
        raw=raw,
        value=SIGN * raw,
        knowledge_dt=knowledge_dt,
        pit_grade=pit_grade,
    )
