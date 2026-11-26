"""把业绩公告事件与 ROE/股东权益/利润序列收成 ``event_delta_roe`` 因子长表行。不写文件。

事件驱动稀疏因子，``event_dt = declare_date``（不依赖行情，区别于 event_aog 的 open_date）。
``knowledge_dt`` 箍到 declare_date。域判定用 declare 后首个交易日（裁定 B1，与 event_sue 同——
非交易日 declare 无 all_a/ST 截面）。同股同公告日多报告期按 ``(declare_date, asset_id)`` AVG 聚合
（复现下游消费粒度，与 event_sue/event_aog 同一裁定）。

逐事件 PIT：ROE 按 ``ann_dt <= declare_date`` 裁剪（契约字段）；利润序列 ``get_profit`` 也按
``declare_date <= declare_date`` 裁剪。股东权益**不**按 declare_date 裁剪（复现旧代码
``get_shrhldr_eqt`` 不按公告日截止——潜在前视，golden 登记）。

事件候选构建与 event_sue/event_aog 共享（月份/时效过滤 + 多源先到先得去重）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from typing import TYPE_CHECKING

from quantagent.domain.feature_lineage import derive_feature_lineage
from quantagent.domain.feature_value import FeatureValue
from quantagent.features.library.fundamental.event_delta_roe import (
    DEFINITION_VERSION,
    FEATURE_ID,
    PARAM_HASH,
    event_delta_roe,
    last_period,
    recomputed_roe,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date, datetime

    from quantagent.domain.fundamental.types import (
        EarningsEventRecord,
        ProfitSeriesRecord,
        RoeRecord,
        ShareholderEquityRecord,
    )

# 公告月份只取这些（剔除业绩修正期）。与 event_sue/event_aog 同一规则。
_VALID_DECLARE_MONTHS = frozenset({1, 2, 3, 4, 7, 8, 10})
# 公告日距报告期超过 4×31 天剔除（超晚披露）。
_MAX_DECLARE_LAG_DAYS = 4 * 31
# 万元换算：股东权益与 fin_income_gen.np_shareholder 单位元，÷10000 转万。
_YUAN_TO_WAN = 10000.0
# 一季报 quarter 代码。Q1 单季净利直接用累计值（累计即单季）。
_Q1 = 1001


@dataclass(frozen=True, slots=True)
class EventDeltaRoeBuild:
    values: tuple[FeatureValue, ...]
    # 经月份/时效过滤后的候选事件数。区分“合法空”（非披露期本无事件）与“异常空”。
    candidate_count: int


def build_event_delta_roe_values(
    *,
    events: Sequence[EarningsEventRecord],
    roe_rows: Sequence[RoeRecord],
    equity_rows: Sequence[ShareholderEquityRecord],
    profit_rows: Sequence[ProfitSeriesRecord],
    domain_by_day: Mapping[date, frozenset[str]],
    computed_at: datetime,
    run_id: str,
) -> EventDeltaRoeBuild:
    """逐事件计算。不满足过滤、缺 roe_last、无法产值的事件不落行（缺失不补 0）。

    ``domain_by_day`` 键是交易日（declare 后首个交易日用于非交易日 declare 的域判定）。
    """
    roe_by_code = _group_roe(roe_rows)
    equity_by_code = _group_equity(equity_rows)
    profit_by_code = _group_profit(profit_rows)
    candidates = _dedup_events(events)
    candidate_count = len(candidates)

    per_event: dict[tuple[date, str], list[float]] = {}
    lineage_inputs: dict[tuple[date, str], list[tuple[date, str]]] = {}
    for event in candidates:
        # 域判定：declare 后首个交易日的域（非交易日 declare 无截面，裁定 B1）。
        domain_dt = _resolve_domain_date(event.declare_dt, domain_by_day)
        if domain_dt is None:
            continue
        if event.asset_id not in domain_by_day[domain_dt]:
            continue
        value, used = _delta_roe_for_event(
            event,
            roe_by_code.get(event.asset_id, ()),
            equity_by_code.get(event.asset_id, ()),
            profit_by_code.get(event.asset_id, ()),
        )
        if value is None:
            continue
        key = (event.declare_dt, event.asset_id)
        per_event.setdefault(key, []).append(float(value))
        slot = lineage_inputs.setdefault(key, [(event.declare_dt, "A")])
        slot.extend(used)

    # 同 (declare_date, asset_id) AVG 聚合，对齐下游消费粒度。event_dt=declare_date。
    values: list[FeatureValue] = []
    for (declare_dt, asset_id), droe_list in sorted(per_event.items()):
        averaged = sum(droe_list) / len(droe_list)
        knowledge_dt, pit_grade = derive_feature_lineage(lineage_inputs[(declare_dt, asset_id)])
        # 因子在 declare_date 收盘后即可知（不依赖行情），箍到 declare_date。
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
    return EventDeltaRoeBuild(values=tuple(values), candidate_count=candidate_count)


def _delta_roe_for_event(
    event: EarningsEventRecord,
    roe_rows: Sequence[RoeRecord],
    equity_rows: Sequence[ShareholderEquityRecord],
    profit_rows: Sequence[ProfitSeriesRecord],
) -> tuple[float | None, list[tuple[date, str]]]:
    """单个事件的 delta_roe。返回 (值, 血缘输入列表)；无法产值返回 (None, [])。"""
    used: list[tuple[date, str]] = []
    cur_period = _period_str(event.report_year, event.report_quarter)
    # period_ly 是去年同期：年份-1，同 mmdd。
    period_ly = _period_str(event.report_year - 1, event.report_quarter)

    # 逐事件 PIT：ROE 行按 ann_dt <= declare_date 裁剪。
    roe_visible = [r for r in roe_rows if r.ann_dt <= event.declare_dt]
    # roe_last：period_ly 的最后一行（按 ann_dt 排序取最新）。period_ly 不在则不产值（硬条件）。
    roe_last = _latest_roe(roe_visible, period_ly)
    if roe_last is None:
        return None, []
    used.append((event.declare_dt, "A"))

    # 当期 roe：Wind 优先；缺失则 profit 重算。
    roe_current = _latest_roe(roe_visible, cur_period)
    if roe_current is None:
        roe_current = _recompute_roe_for_event(event, equity_rows, profit_rows)

    value = event_delta_roe(roe_current=roe_current, roe_last=roe_last)
    if value is None:
        return None, []
    return value, used


def _recompute_roe_for_event(
    event: EarningsEventRecord,
    equity_rows: Sequence[ShareholderEquityRecord],
    profit_rows: Sequence[ProfitSeriesRecord],
) -> float | None:
    """profit 重算分支（Wind ROE 缺失时）：``100 * profit_q / eqt``。任一输入缺失返回 None。

    ``eqt`` 是上一期股东权益（÷10000 转万）；``profit_q`` 单季利润，Q1 用累计、否则减上一期累计。
    """
    if event.profit is None:
        return None
    profit = float(event.profit)  # 万元，端口已统一换算
    lp_year, lp_quarter = last_period(event.report_year, event.report_quarter)
    eqt = _equity_at(equity_rows, _period_str(lp_year, lp_quarter))
    if eqt is None:
        return None
    equity_wan = float(eqt) / _YUAN_TO_WAN
    # profit_q 单季：Q1 直接累计，否则 profit - get_profit(上一期)。
    if event.report_quarter == _Q1:
        profit_q = profit
    else:
        profit_lp = _profit_at(profit_rows, lp_year, lp_quarter, event.declare_dt)
        if profit_lp is None:
            return None
        profit_q = profit - profit_lp
    return recomputed_roe(profit_q=profit_q, equity_wan=equity_wan)


def _latest_roe(roe_rows: Sequence[RoeRecord], period: str) -> float | None:
    """指定 report_period 的最后（ann_dt 最新）非空 S_QFA_ROE。roe_rows 已按 ann_dt 裁剪。

    复现旧代码 ``order by ANN_DT`` 后 ``iloc[-1]``：同 period 多次公告取 ann_dt 最新一行。
    返回 None 表示该 period 无行或最新行 S_QFA_ROE 为空（触发 profit 重算/或不产值）。
    """
    matched = [r for r in roe_rows if _period_str_date(r.report_period) == period]
    if not matched:
        return None
    latest = max(matched, key=lambda r: r.ann_dt)
    if latest.s_qfa_roe is None:
        return None
    return float(latest.s_qfa_roe)


def _equity_at(equity_rows: Sequence[ShareholderEquityRecord], period: str) -> float | None:
    """指定 report_period 的股东权益（元）。多行取 ann_dt 最新（修订优先）。缺失返回 None。"""
    matched = [r for r in equity_rows if _period_str_date(r.report_period) == period]
    if not matched:
        return None
    latest = max(matched, key=lambda r: r.ann_dt)
    if latest.shrhldr_eqt is None:
        return None
    return float(latest.shrhldr_eqt)


def _profit_at(
    profit_rows: Sequence[ProfitSeriesRecord],
    report_year: int,
    report_quarter: int,
    declare_dt: date,
) -> float | None:
    """``get_profit``：指定 report_year/report_quarter 的累计归母净利（万元），``declare_date`` 截止。

    ``profit_rows`` 已是该股全部利润序列（panel 按 asset 分组后传入）。复现旧代码
    ``report_type desc`` 取首行——1003 调整版优先于 1001。``np_shareholder`` 元 ÷10000。
    缺失返回 None。
    """
    best: ProfitSeriesRecord | None = None
    for row in profit_rows:
        if (
            row.report_year == report_year
            and row.report_quarter == report_quarter
            and row.declare_dt <= declare_dt
            and row.np_shareholder is not None
            and (best is None or row.report_type > best.report_type)
        ):
            best = row
    if best is None or best.np_shareholder is None:
        return None
    return float(best.np_shareholder) / _YUAN_TO_WAN


def _period_str(report_year: int, report_quarter: int) -> str:
    """``(report_year, report_quarter)`` → YYYYMMDD 字符串。报告期末日。"""
    month_day = {1001: (3, 31), 1002: (6, 30), 1003: (9, 30), 1004: (12, 31)}[report_quarter]
    return f"{report_year}{month_day[0]:02d}{month_day[1]:02d}"


def _period_str_date(period: date) -> str:
    """report_period date → YYYYMMDD 字符串（与 _period_str 对齐比较）。"""
    return period.strftime("%Y%m%d")


def _group_roe(rows: Sequence[RoeRecord]) -> dict[str, tuple[RoeRecord, ...]]:
    grouped: dict[str, list[RoeRecord]] = {}
    for row in rows:
        grouped.setdefault(row.asset_id, []).append(row)
    return {code: tuple(items) for code, items in grouped.items()}


def _group_equity(
    rows: Sequence[ShareholderEquityRecord],
) -> dict[str, tuple[ShareholderEquityRecord, ...]]:
    grouped: dict[str, list[ShareholderEquityRecord]] = {}
    for row in rows:
        grouped.setdefault(row.asset_id, []).append(row)
    return {code: tuple(items) for code, items in grouped.items()}


def _group_profit(rows: Sequence[ProfitSeriesRecord]) -> dict[str, tuple[ProfitSeriesRecord, ...]]:
    grouped: dict[str, list[ProfitSeriesRecord]] = {}
    for row in rows:
        grouped.setdefault(row.asset_id, []).append(row)
    return {code: tuple(items) for code, items in grouped.items()}


def _resolve_domain_date(declare_dt: date, domain_by_day: Mapping[date, frozenset[str]]) -> date | None:
    """域判定截面日：declare 是交易日直接用；否则取 declare 后首个交易日（裁定 B1，同 event_sue）。"""
    if declare_dt in domain_by_day:
        return declare_dt
    after = sorted(dt for dt in domain_by_day if dt > declare_dt)
    return after[0] if after else None


def _dedup_events(events: Sequence[EarningsEventRecord]) -> list[EarningsEventRecord]:
    """月份+时效过滤后，按事件键 ``(declare_date, asset_id, period)`` 先到先得去重。"""
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
