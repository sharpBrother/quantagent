"""把业绩公告事件与开盘行情收成 ``event_aog`` 因子长表行。不写文件，不接受手填可见日或 PIT 等级。

与 event_sue 同为事件驱动稀疏因子，但输入是**开盘行情**而非历史利润序列。核心差异在
``event_dt`` 语义：event_aog 的因子值描述 **open_date 的开盘跳空**（个股夜盘涨幅 − 指数夜盘涨幅），
且依赖 open_date 行情才能算出——因此 ``event_dt = open_date``（= 旧仓 confirm_date，下游
``alpha_factory/etf/gateway.py`` 注释：``event_*`` 的 effective date 是 confirm_date），
``knowledge_dt`` 箍到 open_date。若错用 declare_date 作 event_dt，会在开盘前前视未知的开盘涨幅。

开盘日判定（``open_date``，负责人 2026-11-26 裁定沿用旧仓 ``entrytime`` 逻辑）：

- ``reflect_same_day`` 判当日/次日；当日取"首个 >= declare 的交易日"，次日取"首个 > declare 的交易日"。
- ``entrytime`` 是市场微观结构建模字段（开盘价何时消化财报），**不是** PIT 可见性字段——
  事件候选的可见性截止仍是 declare_date（grade A），两者职责不同。

事件候选构建与 event_sue 共享（月份/时效过滤 + 多源先到先得去重，复现旧仓 ``process_event``）。
同股同公告日的多报告期事件：``open_date`` 只取决于 (declare_date, entrytime)，与 report_period 无关，
故同 ``(open_date, asset_id)`` 的多个 aog 通常相等；仍按 AVG 聚合对齐下游消费语义
（``AVG(...) GROUP BY confirm_date, stock_code``，与 event_sue 同一裁定）。

血缘由实际进入计算的输入推导：事件的 declare_date + open_date 个股行情 + open_date 指数行情。
行情（``ashareeodprices``/``aindexeodprices``）pit_grade 取源表等级，整体沿木桶取最差。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from typing import TYPE_CHECKING

from quantagent.domain.feature_lineage import derive_feature_lineage
from quantagent.domain.feature_value import FeatureValue
from quantagent.features.library.fundamental.event_aog import (
    BENCHMARK_INDEX,
    DEFINITION_VERSION,
    FEATURE_ID,
    PARAM_HASH,
    event_aog,
    night_ratio,
    reflect_same_day,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date, datetime

    from quantagent.domain.fundamental.types import EarningsEventRecord
    from quantagent.domain.index_returns.types import IndexReturn
    from quantagent.domain.prices.types import DailyPrice

# 公告月份只取这些（剔除业绩修正期）。与 event_sue 同一规则，复现旧仓 process_event。
_VALID_DECLARE_MONTHS = frozenset({1, 2, 3, 4, 7, 8, 10})
# 公告日距报告期超过 4×31 天剔除（超晚披露）。
_MAX_DECLARE_LAG_DAYS = 4 * 31


@dataclass(frozen=True, slots=True)
class EventAogBuild:
    values: tuple[FeatureValue, ...]
    # 经月份/时效过滤后的候选事件数。区分“合法空”（非披露期本无事件）与“异常空”（有候选却全未产值）。
    candidate_count: int


def build_event_aog_values(
    *,
    events: Sequence[EarningsEventRecord],
    stock_prices: Sequence[DailyPrice],
    index_returns: Sequence[IndexReturn],
    open_day_set: frozenset[date],
    domain_by_day: Mapping[date, frozenset[str]],
    computed_at: datetime,
    run_id: str,
) -> EventAogBuild:
    """逐事件计算。不满足过滤、无法解析 open_date、缺行情的事件不落行（缺失不补 0）。

    ``stock_prices``/``index_returns`` 是 open_date 附近窗口的行情（含 adj_open/adj_preclose 与
    open/preclose）。``open_day_set`` 是开市日集合，用于把 declare 当日/次日解析成具体交易日。
    ``domain_by_day`` 键是事件 declare 日的股票域（all_a 减 ST）；事件 declare 日不在域内剔除——
    域判定在事件发生日（与 event_sue 一致），而非 open_date。
    """
    stock_nr = _stock_night_ratio_index(stock_prices)
    index_nr = _index_night_ratio_index(index_returns)
    opens = sorted(open_day_set)
    candidates = _dedup_events(events)
    candidate_count = len(candidates)

    # 逐事件算 aog，按 (open_date, asset_id) 分组。open_date 由 (declare, entrytime) 决定，
    # 与 report_period 无关，故同股同公告日多报告期通常落同一 open_date、算同值。
    per_event: dict[tuple[date, str], list[float]] = {}
    lineage_inputs: dict[tuple[date, str], list[tuple[date, str]]] = {}
    for event in candidates:
        # 先解析 open_date（必是交易日），再用 open_date 的域过滤。财报可在任意自然日 declare
        # （周末/节假日是披露高峰，wx2 19.5% 事件行来自非交易日 declare），非交易日没有 all_a/ST
        # 截面；aog 描述 open_date 的市场反应，股票须在 open_date 是域内可交易股票才有意义，
        # 故域判定在 open_date 而非 declare 日（负责人 2026-11-26 裁定 A1）。
        open_dt = _resolve_open_date(event, opens)
        if open_dt is None:
            continue
        domain = domain_by_day.get(open_dt)
        if domain is None or event.asset_id not in domain:
            continue
        s_nr = stock_nr.get((open_dt, event.asset_id))
        i_nr = index_nr.get((open_dt, BENCHMARK_INDEX))
        if s_nr is None or i_nr is None:
            continue
        value = event_aog(stock_night_ratio=s_nr, index_night_ratio=i_nr)
        key = (open_dt, event.asset_id)
        per_event.setdefault(key, []).append(float(value))
        # 血缘：事件 declare + open_date 行情（个股/指数同为 open_date，记一次）。
        slot = lineage_inputs.setdefault(key, [(event.declare_dt, "A")])
        slot.append((open_dt, "A"))

    # 同 (open_date, asset_id) AVG 聚合，对齐下游消费粒度。长表键不含 report_period。
    values: list[FeatureValue] = []
    for (open_dt, asset_id), aog_list in sorted(per_event.items()):
        averaged = sum(aog_list) / len(aog_list)
        knowledge_dt, pit_grade = derive_feature_lineage(lineage_inputs[(open_dt, asset_id)])
        # 因子值依赖 open_date 行情，截面在 open_date 形成可见，箍到 open_date。
        knowledge_dt = max(knowledge_dt, open_dt)
        values.append(
            FeatureValue(
                event_dt=open_dt,
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
    return EventAogBuild(values=tuple(values), candidate_count=candidate_count)


def _resolve_open_date(event: EarningsEventRecord, opens: Sequence[date]) -> date | None:
    """把 declare 当日/次日解析成具体交易日。无足够未来交易日返回 None（物化窗口末尾）。

    当日反映 → 首个 >= declare 的交易日；次日反映 → 首个 > declare 的交易日。复现旧仓
    ``trade_date[trade_date >= declare].iloc[0]`` / ``> declare``。
    """
    same_day = reflect_same_day(event.entrytime, event.declare_dt)
    if same_day:
        after = tuple(dt for dt in opens if dt >= event.declare_dt)
    else:
        after = tuple(dt for dt in opens if dt > event.declare_dt)
    if not after:
        return None
    return after[0]


def _stock_night_ratio_index(rows: Sequence[DailyPrice]) -> dict[tuple[date, str], float]:
    """个股 ``100*(adj_open/adj_preclose-1)``，键 (trade_dt, wind_code)。缺失不复权价不落键。"""
    out: dict[tuple[date, str], float] = {}
    for row in rows:
        if row.adj_open is None or row.adj_preclose is None:
            continue
        nr = night_ratio(float(row.adj_open), float(row.adj_preclose))
        if nr is not None:
            out[(row.trade_dt, row.wind_code)] = nr
    return out


def _index_night_ratio_index(rows: Sequence[IndexReturn]) -> dict[tuple[date, str], float]:
    """指数 ``100*(open/preclose-1)``，键 (trade_dt, wind_code)。缺失开盘价不落键。"""
    out: dict[tuple[date, str], float] = {}
    for row in rows:
        if row.open is None or row.preclose is None:
            continue
        nr = night_ratio(float(row.open), float(row.preclose))
        if nr is not None:
            out[(row.trade_dt, row.wind_code)] = nr
    return out


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
    """报告期末日：1001→0331、1002→0630、1003→0930、1004→1231。"""
    month_day = {1001: (3, 31), 1002: (6, 30), 1003: (9, 30), 1004: (12, 31)}[report_quarter]
    return date_type(report_year, month_day[0], month_day[1])
