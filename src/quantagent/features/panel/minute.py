"""分钟因子面板：逐个开市日经 ``as_of`` 读取分钟行情，算日值，再取截至 event_dt 的五日均值。

不写文件，也不接受手填可见日。可见日与 ``pit_grade`` 由窗口内五个开市日的血缘推导。

股票范围按截面日给出（``universe_at``）：输出只包含截面日股票池内的股票，读取时取窗口内各截面日
股票池的并集。

排除日的处理（负责人 2026-11-24 裁定）：分区里被排除的股票在该日没有分钟行，视为当日无日值，
不进入五日均值，也不中断运行。排除集从 ``MinuteBarRepository.excluded_codes`` 取得，读取时从请求
代码中减去。减完为空则该日没有任何股票的日值。

已知口径差异（负责人裁定或待裁定，见报告）：

- 旧代码 ``float_mv`` 缺失会丢掉该股票整日。这里不读 ``float_mv``，缺这一项的股票日会有值，
  旧表里没有。
- 旧代码 ``ratio_*`` 在上涨或下跌不超过 1 根时为假 0，这里记为缺失。
- 旧代码 ``real_kurt`` 在收益全相同时为假 0，这里记为缺失。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from quantagent.domain.errors import EmptyDomainError, FeatureLookupError
from quantagent.domain.feature_lineage import derive_feature_lineage
from quantagent.domain.feature_value import FeatureValue
from quantagent.features.library.minute.five_day import (
    DEFINITION_VERSION,
    SIGN,
    SPECS,
    WINDOW_OPEN_DAYS,
    window_mean,
)
from quantagent.features.library.minute.intraday import MinuteDayStats, minute_day_stats

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Sequence
    from datetime import date, datetime

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.ports.minute_bar import MinuteBarRepository

MINUTE_COLUMNS: tuple[str, ...] = ("ts_code", "trade_time", "close", "vol")
_ASSET_CLASS = "stock"
_SUPPORTED_RULE = "same_day_close"


def build_minute_factor_values(
    repo: MinuteBarRepository,
    *,
    as_of: date,
    opens: Sequence[date],
    start: date,
    end: date,
    contract: VisibilityContract,
    universe_at: Callable[[date], Sequence[str]],
    computed_at: datetime,
    run_id: str,
) -> tuple[FeatureValue, ...]:
    """``opens`` 是升序的开市日，须覆盖 ``start`` 之前至少 4 个开市日。

    ``universe_at(d)`` 给出截面日 ``d`` 的股票池。每个 ``event_dt`` 取它及之前共 5 个开市日的
    日值均值，只输出 ``event_dt`` 截面股票池内的股票。窗口内全部缺失则不产行。
    """
    if contract.visibility.rule != _SUPPORTED_RULE:
        # 日值 knowledge_dt 直接取交易日，只对 same_day_close 成立。其他规则需另行设计。
        raise FeatureLookupError(
            f"分钟因子只支持 {_SUPPORTED_RULE}，当前为 {contract.visibility.rule}"
        )
    ordered = tuple(opens)
    if list(ordered) != sorted(set(ordered)):
        raise FeatureLookupError("开市日必须升序且不重复")
    targets = [i for i, day in enumerate(ordered) if start <= day <= end]
    if not targets:
        raise EmptyDomainError("区间内没有开市日")
    first, last = targets[0], targets[-1]
    if first < WINDOW_OPEN_DAYS - 1:
        raise FeatureLookupError("开市日历在起点之前不足 5 个开市日")

    universe = {ordered[idx]: frozenset(universe_at(ordered[idx])) for idx in targets}
    daily: dict[date, dict[str, MinuteDayStats]] = {}
    for idx in range(first - (WINDOW_OPEN_DAYS - 1), last + 1):
        day = ordered[idx]
        # 读取范围：所有窗口包含 day 的截面日的股票池并集。
        wanted: set[str] = set()
        for t in range(max(first, idx), min(last, idx + WINDOW_OPEN_DAYS - 1) + 1):
            wanted.update(universe[ordered[t]])
        daily[day] = load_daily_stats(repo, as_of=as_of, day=day, codes=wanted)

    grade = contract.visibility.grade
    values: list[FeatureValue] = []
    for idx in targets:
        event_dt = ordered[idx]
        window = ordered[idx - (WINDOW_OPEN_DAYS - 1) : idx + 1]
        # 五个开市日都是输入，即使某只股票某天没有行，依赖关系也已确定。
        knowledge_dt, pit_grade = derive_feature_lineage(tuple((day, grade) for day in window))
        for code in sorted(universe[event_dt]):
            for spec in SPECS:
                samples = [
                    getattr(daily[day][code], spec.stat) if code in daily[day] else None
                    for day in window
                ]
                mean = window_mean(samples)
                if mean is None:
                    continue
                values.append(
                    FeatureValue(
                        event_dt=event_dt,
                        asset_id=code,
                        asset_class=_ASSET_CLASS,
                        feature_id=spec.feature_id,
                        definition_version=DEFINITION_VERSION,
                        param_hash=spec.param_hash,
                        value=SIGN * mean,
                        knowledge_dt=knowledge_dt,
                        pit_grade=pit_grade,
                        computed_at=computed_at,
                        run_id=run_id,
                    )
                )
    return tuple(values)


def load_daily_stats(
    repo: MinuteBarRepository,
    *,
    as_of: date,
    day: date,
    codes: Collection[str],
) -> dict[str, MinuteDayStats]:
    """读取 ``day`` 当日 ``codes`` 中股票的日值。排除集（见模块说明）从请求中减去。

    返回只含有分钟行的股票。被排除或当日没有分钟行的股票不在结果中，即当日无日值。
    """
    excluded = repo.excluded_codes(as_of=as_of, day=day)
    requested = sorted(code for code in codes if code not in excluded)
    if not requested:
        # 减去排除集后为空：该日所有股票都没有日值。
        return {}
    table = repo.scan_window(
        as_of=as_of, start=day, end=day, codes=requested, columns=MINUTE_COLUMNS
    )
    return _day_stats(table.to_pylist(), day)


def _day_stats(rows: Sequence[dict[str, Any]], day: date) -> dict[str, MinuteDayStats]:
    """按股票分组，并按 trade_time 升序算日值。行的日期必须等于 ``day``。"""
    by_code: dict[str, list[tuple[datetime, float, float]]] = {}
    for row in rows:
        stamp = row["trade_time"]
        if stamp.date() != day:
            raise FeatureLookupError(f"分钟行的日期 {stamp.date()} 不等于 {day}")
        by_code.setdefault(str(row["ts_code"]), []).append(
            (stamp, float(row["close"]), float(row["vol"]))
        )
    stats: dict[str, MinuteDayStats] = {}
    for code, items in by_code.items():
        items.sort(key=lambda item: item[0])
        if len({item[0] for item in items}) != len(items):
            raise FeatureLookupError(f"{code} 在 {day} 存在重复的 trade_time")
        stats[code] = minute_day_stats(
            [item[1] for item in items],
            [item[2] for item in items],
        )
    return stats
