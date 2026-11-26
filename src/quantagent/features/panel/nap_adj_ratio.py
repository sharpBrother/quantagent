"""把盈利预测调整的截面输入收成因子长表行。不写文件，也不接受手填的可见日或 PIT 等级。

截面由调用方给出：``domain_by_day`` 是每个交易日的股票域（all_a 去掉当日 ST）。只有交易日才有截面。
血缘由实际读取的输入推导：每条进入计算的输入行按 ``entrytime``（可见日）和契约等级进入
``derive_feature_lineage``，因此 ``knowledge_dt`` 是输入中最晚的入库日，``pit_grade`` 是输入中最差的等级。
这与 did_ratio 的差别：did_ratio 用 ANN_DT（既是窗口列又是可见列），本因子窗口列是
``current_create_date``、可见列是 ``entrytime``，血缘取后者。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from quantagent.domain.feature_lineage import derive_feature_lineage
from quantagent.domain.feature_value import FeatureValue
from quantagent.features.library.fundamental.nap_adj_ratio import (
    DEFINITION_VERSION,
    FEATURE_ID,
    PARAM_HASH,
    adjust_window_rows,
    nap_adj_ratio,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date, datetime

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.fundamental.types import EarningsAdjustRecord


@dataclass(frozen=True, slots=True)
class NapAdjBuild:
    values: tuple[FeatureValue, ...]


def build_nap_adj_ratio_values(
    *,
    domain_by_day: Mapping[date, frozenset[str]],
    rows: Sequence[EarningsAdjustRecord],
    contract: VisibilityContract,
    computed_at: datetime,
    run_id: str,
) -> NapAdjBuild:
    """逐交易日、逐股票计算。窗口内无有效行的股票不落行（缺失不补 0）。

    血缘只取实际进入计算的输入行（已按 entrytime 与业务窗口裁剪），可见日取 ``entrytime``。
    """
    grade = contract.visibility.grade
    by_code = _group_by_asset(rows)

    values: list[FeatureValue] = []
    for day in sorted(domain_by_day):
        for code in sorted(domain_by_day[day]):
            candidates = by_code.get(code)
            if candidates is None:
                continue
            value = nap_adj_ratio(as_of=day, rows=candidates)
            if value is None:
                continue
            # 血缘只取实际进入计算的输入行，与库函数同一份裁剪逻辑，保证一致。
            window = adjust_window_rows(as_of=day, rows=candidates)
            inputs = [(row.entry_dt, grade) for row in window]
            knowledge_dt, pit_grade = derive_feature_lineage(inputs)
            # knowledge_dt 的语义是“该截面值最早何时可见/可用”，与其他因子一致：截面在 event_dt
            # 才形成可见（窗口右端点就是 event_dt，当日是否还有新调整进来要到 event_dt 才确定）。
            # 稀疏事件输入的最晚入库日可能早于 event_dt，须箍到 event_dt——这不是抬升，与行情因子
            # “当日行情是输入故 knowledge_dt=event_dt”是同一语义，只是本因子没有当日输入需显式箍制。
            knowledge_dt = max(knowledge_dt, day)
            values.append(
                FeatureValue(
                    event_dt=day,
                    asset_id=code,
                    asset_class="stock",
                    feature_id=FEATURE_ID,
                    definition_version=DEFINITION_VERSION,
                    param_hash=PARAM_HASH,
                    value=float(value),
                    knowledge_dt=knowledge_dt,
                    pit_grade=pit_grade,
                    computed_at=computed_at,
                    run_id=run_id,
                )
            )
    return NapAdjBuild(values=tuple(values))


def _group_by_asset(
    rows: Sequence[EarningsAdjustRecord],
) -> dict[str, tuple[EarningsAdjustRecord, ...]]:
    """按股票分组，组内按 entrytime 升序。面板按 entrytime 二分取候选。"""
    grouped: dict[str, list[EarningsAdjustRecord]] = {}
    for row in rows:
        grouped.setdefault(row.asset_id, []).append(row)
    return {
        code: tuple(sorted(items, key=lambda item: item.entry_dt))
        for code, items in grouped.items()
    }
