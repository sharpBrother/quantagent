"""把三个资金流因子收成因子长表行：ABSO 的 UMR 用开市日窗口，两个单股票因子用个股自有的 20 行窗口。
不写文件，也不接受手填可见日。窗口不足或值无定义时不产行。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.domain.feature_value import FeatureValue
from quantagent.features.library.money_flow import abso_umr, actlargemedcut, moneyflowh
from quantagent.features.library.money_flow.abso_umr import (
    abso_umr_from_maps,
    reject_invalid_abso_umr_inputs,
)
from quantagent.features.window import last_n_trading_days

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date, datetime

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.index_returns.types import IndexReturn
    from quantagent.domain.money_flow.types import MoneyFlow
    from quantagent.domain.prices.types import DailyPrice


def build_money_flow_factor_values(
    prices: Sequence[DailyPrice],
    money_flows: Sequence[MoneyFlow],
    index_returns: Sequence[IndexReturn],
    open_days: Sequence[date],
    *,
    price_contract: VisibilityContract,
    money_flow_contract: VisibilityContract,
    index_contract: VisibilityContract,
    start: date,
    end: date,
    computed_at: datetime,
    run_id: str,
) -> tuple[FeatureValue, ...]:
    """只产 ``[start, end]`` 内的截面。``open_days`` 必须包含窗口需要的前序开市日。

    ``abso_umr`` 的窗口按 ``open_days`` 往前数 69 个开市日。
    ``moneyflowh`` 与 ``actlargemedcut`` 的窗口按个股自有行往前数 20 行，与旧仓 ``tail(20)`` 一致。
    """
    reject_invalid_abso_umr_inputs(open_days, prices, money_flows, index_returns)
    opens = tuple(sorted(open_days))
    prices_by_code: dict[str, list[DailyPrice]] = {}
    for row in prices:
        prices_by_code.setdefault(row.wind_code, []).append(row)
    flows_by_code: dict[str, dict[date, MoneyFlow]] = {}
    for flow in money_flows:
        flows_by_code.setdefault(flow.wind_code, {})[flow.trade_dt] = flow
    index_by_day = {row.trade_dt: row for row in index_returns}

    values: list[FeatureValue] = []
    for code in sorted(set(prices_by_code) | set(flows_by_code)):
        series = sorted(prices_by_code.get(code, []), key=lambda row: row.trade_dt)
        flows = flows_by_code.get(code, {})
        price_by_day = {row.trade_dt: row for row in series}
        common = {
            "price_contract": price_contract,
            "money_flow_contract": money_flow_contract,
        }
        for event in series:
            if event.trade_dt < start or event.trade_dt > end:
                continue
            window = last_n_trading_days(
                series,
                event_dt=event.trade_dt,
                count=moneyflowh.WINDOW,
                trade_dt=lambda item: item.trade_dt,
            )
            if window is None:
                continue
            flow_value = moneyflowh.moneyflowh_value(window, flows, **common)
            if flow_value is not None:
                values.append(
                    _row(
                        event_dt=flow_value.event_dt,
                        asset_id=flow_value.asset_id,
                        feature_id=moneyflowh.FEATURE_ID,
                        definition_version=moneyflowh.DEFINITION_VERSION,
                        param_hash=moneyflowh.PARAM_HASH,
                        value=float(flow_value.value),
                        knowledge_dt=flow_value.knowledge_dt,
                        pit_grade=flow_value.pit_grade,
                        computed_at=computed_at,
                        run_id=run_id,
                    )
                )
            cut_value = actlargemedcut.actlargemedcut_value(window, flows, **common)
            if cut_value is not None:
                values.append(
                    _row(
                        event_dt=cut_value.event_dt,
                        asset_id=cut_value.asset_id,
                        feature_id=actlargemedcut.FEATURE_ID,
                        definition_version=actlargemedcut.DEFINITION_VERSION,
                        param_hash=actlargemedcut.PARAM_HASH,
                        value=float(cut_value.value),
                        knowledge_dt=cut_value.knowledge_dt,
                        pit_grade=cut_value.pit_grade,
                        computed_at=computed_at,
                        run_id=run_id,
                    )
                )
        window_len = abso_umr.LOOKBACK
        for index, event_dt in enumerate(opens):
            if event_dt < start or event_dt > end or index < window_len - 1:
                continue
            days = opens[index - (window_len - 1) : index + 1]
            abso_value = abso_umr_from_maps(
                days,
                price_by_day=price_by_day,
                flow_by_day=flows,
                index_by_day=index_by_day,
                asset_id=code,
                price_contract=price_contract,
                money_flow_contract=money_flow_contract,
                index_contract=index_contract,
            )
            if abso_value is None:
                continue
            values.append(
                _row(
                    event_dt=abso_value.event_dt,
                    asset_id=abso_value.asset_id,
                    feature_id=abso_umr.FEATURE_ID,
                    definition_version=abso_umr.DEFINITION_VERSION,
                    param_hash=abso_umr.PARAM_HASH,
                    value=float(abso_value.value),
                    knowledge_dt=abso_value.knowledge_dt,
                    pit_grade=abso_value.pit_grade,
                    computed_at=computed_at,
                    run_id=run_id,
                )
            )
    return tuple(values)


def _row(
    *,
    event_dt: date,
    asset_id: str,
    feature_id: str,
    definition_version: str,
    param_hash: str,
    value: float,
    knowledge_dt: date,
    pit_grade: str,
    computed_at: datetime,
    run_id: str,
) -> FeatureValue:
    return FeatureValue(
        event_dt=event_dt,
        asset_id=asset_id,
        asset_class="stock",
        feature_id=feature_id,
        definition_version=definition_version,
        param_hash=param_hash,
        value=value,
        knowledge_dt=knowledge_dt,
        pit_grade=pit_grade,
        computed_at=computed_at,
        run_id=run_id,
    )
