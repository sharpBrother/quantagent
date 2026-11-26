"""把业绩公告事件与历史利润序列收成 ``event_sue`` 因子长表行。不写文件，不接受手填可见日或 PIT 等级。

与 nap_adj_ratio 的逐日横截面不同，本因子是**事件驱动稀疏**：只在事件公告日（``event_dt``）对
该股票产一行，不逐交易日填。``event_dt`` = 公告日 ``declare_date``；``knowledge_dt`` 由血缘推导
并箍到 ``event_dt``（财报当天收盘后可见，见 nap_adj_ratio ADR 决策 4 的同语义箍制）。

事件候选构建复现旧仓 ``process_event``（行号见 event-factors-handoff.md §2）：

- 月份过滤：公告月份 ∈ {1,2,3,4,7,8,10}（剔除业绩修正期）。
- 时效过滤：公告日距报告期 ≤ 4×31 天（剔除超晚披露）。
- 多源去重：事件键 ``(declare_date, asset_id, period)``，同键按 forecast → income → express
  先到先得（adapter 已按此序返回）。

逐事件 PIT：每只事件用自己的 ``declare_date`` 截止历史利润序列（``declare_date <= 事件.declare_date``），
不是统一的 as_of。这是因为事件发生在不同日期，早期事件不能看到晚期才公告的财报。adapter 批量读时
按 as_of 宽松截止，panel 逐事件再加严。

血缘由实际进入计算的输入推导：事件本身的 declare_date + 参与利润序列的历史行的 declare_date，
pit_grade 取最差（fin_income_gen grade A）。当期事件的 profit 也来自源表，其可见日是事件 declare_date。

**同键多报告期聚合（负责人 2026-11-26 裁定选项 1）**：长表唯一键 ``(event_dt, asset_id, feature_id, ...)``
不含 report_period，但同一股票同一公告日常同时披露多个报告期（年报+一季报，income 源实测 28,821 例），
逐事件会产生同键冲突。复现下游真实消费语义——``alpha_factory/etf/gateway.py`` 读取时
``AVG(CAST(event_sue AS float)) GROUP BY confirm_date, stock_code`` 本就按 `(confirm_date, stock_code)`
求平均——物化时把同 ``(declare_date, asset_id)`` 的多个 sue 求平均写一行。血缘取参与平均的所有事件输入并集。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from typing import TYPE_CHECKING

from quantagent.domain.feature_lineage import derive_feature_lineage
from quantagent.domain.feature_value import FeatureValue
from quantagent.features.library.fundamental.event_sue import (
    DEFINITION_VERSION,
    FEATURE_ID,
    LOOKBACK_YEARS,
    PARAM_HASH,
    event_sue,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date, datetime

    from quantagent.domain.fundamental.types import EarningsEventRecord, ProfitSeriesRecord

# 公告月份只取这些（剔除业绩修正期）。旧代码 event_s['declare_date'].month not in [...]。
_VALID_DECLARE_MONTHS = frozenset({1, 2, 3, 4, 7, 8, 10})
# 公告日距报告期超过 4×31 天剔除（超晚披露）。旧代码 (declare_date - period).days > 4*31。
_MAX_DECLARE_LAG_DAYS = 4 * 31


@dataclass(frozen=True, slots=True)
class EventSueBuild:
    values: tuple[FeatureValue, ...]


def build_event_sue_values(
    *,
    events: Sequence[EarningsEventRecord],
    profit_rows: Sequence[ProfitSeriesRecord],
    domain_by_day: Mapping[date, frozenset[str]],
    computed_at: datetime,
    run_id: str,
) -> EventSueBuild:
    """逐事件计算。不满足过滤或无法产值的事件不落行（缺失不补 0）。

    ``domain_by_day`` 是事件日的股票域（all_a 减当日 ST）；事件日不在域内（或非交易日无域）的事件剔除。
    """
    profit_by_code = _group_profit_by_asset(profit_rows)
    candidates = _dedup_events(events)

    # 第一遍：逐事件算 sue，按 (declare_date, asset_id) 分组收集。同股同公告日的多个报告期
    # （年报+一季报同日披露常见）各自是独立事件、各自算出 sue。
    # 每组记录 (sue 值列表, 血缘输入并集)。
    per_event: dict[tuple[date, str], list[float]] = {}
    lineage_inputs: dict[tuple[date, str], list[tuple[date, str]]] = {}
    for event in candidates:
        if event.profit is None:
            continue
        # 域过滤：事件日必须是有域的交易日，且该股在当日域内。
        domain = domain_by_day.get(event.declare_dt)
        if domain is None or event.asset_id not in domain:
            continue
        history = profit_by_code.get(event.asset_id)
        if history is None:
            continue
        # 逐事件 PIT：历史序列再按该事件 declare_date 截止 + period < 当期 + report_year 回退。
        cur_period = event.report_year * 10000 + event.report_quarter
        min_year = event.report_year - LOOKBACK_YEARS
        event_history = tuple(
            row
            for row in history
            if row.declare_dt <= event.declare_dt
            and row.report_year >= min_year
            and row.report_year * 10000 + row.report_quarter < cur_period
        )
        value = event_sue(
            report_year=event.report_year,
            report_quarter=event.report_quarter,
            profit=float(event.profit),
            history=event_history,
        )
        if value is None:
            continue
        key = (event.declare_dt, event.asset_id)
        per_event.setdefault(key, []).append(float(value))
        # 血缘累积：事件本身 + 该事件实际进入序列的历史行。多事件合并时取并集。
        slot = lineage_inputs.setdefault(key, [(event.declare_dt, "A")])
        slot.extend((row.declare_dt, "A") for row in event_history)

    # 第二遍：同 (declare_date, asset_id) 的多个 sue 求平均，每股票每日一行。
    # 复现下游消费语义（alpha_factory/etf/gateway.py：``AVG(...) GROUP BY confirm_date, stock_code``，
    # 负责人 2026-11-26 裁定选项 1）。长表键不含 report_period，多报告期事件必须聚合才能写入。
    values: list[FeatureValue] = []
    for (declare_dt, asset_id), sue_list in sorted(per_event.items()):
        averaged = sum(sue_list) / len(sue_list)
        knowledge_dt, pit_grade = derive_feature_lineage(lineage_inputs[(declare_dt, asset_id)])
        # 截面在 event_dt 形成可见，箍到 event_dt（与 nap_adj_ratio 同语义，非抬升）。
        knowledge_dt = max(knowledge_dt, declare_dt)
        values.append(
            FeatureValue(
                event_dt=declare_dt,
                asset_id=asset_id,
                asset_class="stock",
                feature_id=FEATURE_ID,
                definition_version=DEFINITION_VERSION,
                param_hash=PARAM_HASH,
                value=float(averaged),
                knowledge_dt=knowledge_dt,
                pit_grade=pit_grade,
                computed_at=computed_at,
                run_id=run_id,
            )
        )
    return EventSueBuild(values=tuple(values))


def _dedup_events(events: Sequence[EarningsEventRecord]) -> list[EarningsEventRecord]:
    """月份+时效过滤后，按事件键 ``(declare_date, asset_id, period)`` 先到先得去重。

    ``events`` 已由 adapter 按 forecast → income → express 排序，setdefault 保留首个即复现旧优先级。
    """
    kept: dict[tuple[date, str, int], EarningsEventRecord] = {}
    for event in events:
        if event.declare_dt.month not in _VALID_DECLARE_MONTHS:
            continue
        period_end = _period_end_date(event.report_year, event.report_quarter)
        if (event.declare_dt - period_end).days > _MAX_DECLARE_LAG_DAYS:
            continue
        period = event.report_year * 10000 + event.report_quarter
        key = (event.declare_dt, event.asset_id, period)
        kept.setdefault(key, event)
    return list(kept.values())


def _period_end_date(report_year: int, report_quarter: int) -> date:
    """报告期末日：1001→0331、1002→0630、1003→0930、1004→1231。旧代码 period_dict 反推。"""
    month_day = {1001: (3, 31), 1002: (6, 30), 1003: (9, 30), 1004: (12, 31)}[report_quarter]
    return date_type(report_year, month_day[0], month_day[1])


def _group_profit_by_asset(
    rows: Sequence[ProfitSeriesRecord],
) -> dict[str, tuple[ProfitSeriesRecord, ...]]:
    grouped: dict[str, list[ProfitSeriesRecord]] = {}
    for row in rows:
        grouped.setdefault(row.asset_id, []).append(row)
    return {code: tuple(items) for code, items in grouped.items()}
