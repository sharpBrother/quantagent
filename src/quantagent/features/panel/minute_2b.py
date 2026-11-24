"""第二批分钟因子面板：``corr_vrlaglarge`` 五日均值，``core_up`` / ``core_down`` 二十日均值并做 pxret21 中性化。

读取与窗口口径同第一批（见 ``minute.py``）：``event_dt = d`` 取截至 d 的窗口，股票池按截面日
``universe_at(d)``，排除集从当日分区读取，被排除的股票当日无日值。

中性化是每个 ``event_dt = d`` 一个截面回归（口径出处见 ``cross_section.py``）：

- y：窗口内日值的均值乘以方向（``core_up`` 为 +1，``core_down`` 为 −1），再做 MAD 去极值。
  旧代码的 direction 乘在聚合之后、去极值之前（``alpha_factory/factor_loader.py`` 第 142、158 行），
  与这里一致。
- x：pxret21(d) = (P(d) − P(d₋₂₀)) / |P(d₋₂₀)|，P 为日行情 ``adj_close``（即 ``S_DQ_ADJCLOSE``）。
  d₋₂₀ 是 d 往前第 20 个开市日，所以用到 21 个开市日的价格点、20 个区间。x 做工具去极值。
  旧端点口径见 ``refresh_performance_factor_fast_ic.py`` 第 2030-2060 行 ``paired_endpoints``：
  两端价格都必须存在，分母为 0 时缺失，不做前值填充。
- 残差 = y − OLS([1, x]) 的拟合。样本为 y 与 x 都有值的股票。残差就是 ``neutral_value``，没有再做标准化。

``knowledge_dt`` 与 ``pit_grade`` 由血缘推导：中性化因子的输入包括窗口内分钟日与两个价格端点日，
取最晚可见日与最差等级。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from quantagent.domain.errors import EmptyDomainError, FeatureLookupError
from quantagent.domain.feature_lineage import derive_feature_lineage
from quantagent.domain.feature_value import FeatureValue
from quantagent.features.library.cross_section import (
    MIN_NEUTRAL_OBS,
    mad_winsorize,
    residualize,
    utility_winsorize,
)
from quantagent.features.library.minute.batch_2b import PARAM_HASHES, minute_day_2b
from quantagent.features.library.minute.five_day import window_mean
from quantagent.features.panel.minute import MINUTE_COLUMNS

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Sequence
    from datetime import date, datetime

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.ports.minute_bar import MinuteBarRepository
    from quantagent.domain.ports.prices import DailyPriceRepository

_SUPPORTED_RULE = "same_day_close"
_ASSET_CLASS = "stock"
DEFINITION_VERSION = "v1"
# 20 个开市日窗口需要 19 个前置日；pxret21 的 d₋₂₀ 还需要再往前一天，共 20 个前置开市日。
WINDOW_CORE = 20
PRICE_LOOKBACK = 20
CORR_WINDOW = 5
CORR_SIGN = -1.0


@dataclass(frozen=True)
class MinuteDay2b:
    """一只股票一个交易日的第二批日值。``None`` 表示该日不产值。"""

    corr_vrlaglarge: float | None
    core_up: float | None
    core_down: float | None


def build_minute_2b_values(
    repo: MinuteBarRepository,
    prices: DailyPriceRepository,
    *,
    as_of: date,
    opens: Sequence[date],
    start: date,
    end: date,
    minute_contract: VisibilityContract,
    price_contract: VisibilityContract,
    universe_at: Callable[[date], Collection[str]],
    computed_at: datetime,
    run_id: str,
    feature_ids: Sequence[str],
) -> tuple[FeatureValue, ...]:
    """返回 ``[start, end]`` 内截面日的第二批因子值。

    ``opens`` 是升序的开市日，须覆盖 ``start`` 之前至少 ``PRICE_LOOKBACK`` 个开市日。
    ``feature_ids`` 选择要产出的因子，三个 id 是 ``batch_2b.PARAM_HASHES`` 的键，供 CLI 分次运行。
    """
    for contract in (minute_contract, price_contract):
        if contract.visibility.rule != _SUPPORTED_RULE:
            # 日值 knowledge_dt 直接取交易日，只对 same_day_close 成立。
            raise FeatureLookupError(
                f"第二批分钟因子只支持 {_SUPPORTED_RULE}，当前为 {contract.visibility.rule}"
            )
    ordered = tuple(opens)
    if list(ordered) != sorted(set(ordered)):
        raise FeatureLookupError("开市日必须升序且不重复")
    targets = [i for i, day in enumerate(ordered) if start <= day <= end]
    if not targets:
        raise EmptyDomainError("区间内没有开市日")
    first, last = targets[0], targets[-1]
    if first < PRICE_LOOKBACK:
        raise FeatureLookupError("开市日历在起点之前不足 20 个开市日")
    wanted_ids = set(feature_ids)
    if not wanted_ids:
        raise FeatureLookupError("feature_ids 为空")
    universe = {ordered[i]: frozenset(universe_at(ordered[i])) for i in targets}

    # 分钟数据只读所选因子需要的窗口：只算 corr 时回看 5 日，含 core 时回看 20 日。
    # 多读会碰到窗口外没有分钟数据的日子（源端 2024-07-30 起），读取端按 fail-closed 报错。
    lookback = WINDOW_CORE if wanted_ids & _CORE_IDS else CORR_WINDOW
    daily: dict[date, dict[str, MinuteDay2b]] = {}
    for idx in range(first - (lookback - 1), last + 1):
        day = ordered[idx]
        # 读取范围：所有窗口包含 day 的截面日股票池的并集。
        wanted: set[str] = set()
        for t in range(max(first, idx), min(last, idx + lookback - 1) + 1):
            wanted.update(universe[ordered[t]])
        daily[day] = load_daily_2b(repo, as_of=as_of, day=day, codes=wanted)

    all_codes = sorted(set().union(*universe.values()))
    price_start = ordered[first - PRICE_LOOKBACK]
    price_end = ordered[last]
    px = _price_index(
        prices.list_prices(
            as_of=as_of,
            start=price_start,
            end=price_end,
            wind_codes=tuple(all_codes),
        )
    )

    grades = _Grades(minute=minute_contract.visibility.grade, price=price_contract.visibility.grade)
    values: list[FeatureValue] = []
    for idx in targets:
        event_dt = ordered[idx]
        scope = universe[event_dt]
        base_day = ordered[idx - PRICE_LOOKBACK]
        win_corr = ordered[idx - (CORR_WINDOW - 1) : idx + 1]
        win_core = ordered[idx - (WINDOW_CORE - 1) : idx + 1]
        if "pf_single_corr_vrlaglarge_5_mean_neg" in wanted_ids:
            values.extend(
                _corr_values(
                    daily=daily,
                    scope=scope,
                    window=win_corr,
                    event_dt=event_dt,
                    grade=grades.minute,
                    computed_at=computed_at,
                    run_id=run_id,
                )
            )
        if wanted_ids & _CORE_IDS:
            values.extend(
                _core_values(
                    daily=daily,
                    scope=scope,
                    window=win_core,
                    px=px,
                    base_day=base_day,
                    event_dt=event_dt,
                    grades=grades,
                    wanted_ids=wanted_ids,
                    computed_at=computed_at,
                    run_id=run_id,
                )
            )
    return tuple(values)


@dataclass(frozen=True)
class _Grades:
    minute: str
    price: str


_CORE_IDS = frozenset(
    {
        "pf_single_core_up_20_mean_pos_neut_pxret21",
        "pf_single_core_down_20_mean_neg_neut_pxret21",
    }
)


def _corr_values(
    *,
    daily: dict[date, dict[str, MinuteDay2b]],
    scope: Collection[str],
    window: Sequence[date],
    event_dt: date,
    grade: str,
    computed_at: datetime,
    run_id: str,
) -> list[FeatureValue]:
    knowledge_dt, pit_grade = derive_feature_lineage(tuple((day, grade) for day in window))
    out: list[FeatureValue] = []
    for code in sorted(scope):
        mean = window_mean([_stat(daily[d], code, "corr_vrlaglarge") for d in window])
        if mean is None:
            continue
        out.append(
            _row(
                event_dt=event_dt,
                code=code,
                feature_id="pf_single_corr_vrlaglarge_5_mean_neg",
                value=CORR_SIGN * mean,
                knowledge_dt=knowledge_dt,
                pit_grade=pit_grade,
                computed_at=computed_at,
                run_id=run_id,
            )
        )
    return out


def _core_values(
    *,
    daily: dict[date, dict[str, MinuteDay2b]],
    scope: Collection[str],
    window: Sequence[date],
    px: dict[tuple[str, date], float],
    base_day: date,
    event_dt: date,
    grades: _Grades,
    wanted_ids: set[str],
    computed_at: datetime,
    run_id: str,
) -> list[FeatureValue]:
    """截面回归：y 为窗口均值（乘方向、MAD 去极值），x 为 pxret21（工具去极值），输出残差。"""
    knowledge_dt, pit_grade = derive_feature_lineage(
        (
            *((day, grades.minute) for day in window),
            (base_day, grades.price),
            (event_dt, grades.price),
        )
    )
    pxret = _pxret_by_code(px, scope, base_day, event_dt)
    out: list[FeatureValue] = []
    for feature_id, stat, sign in (
        ("pf_single_core_up_20_mean_pos_neut_pxret21", "core_up", 1.0),
        ("pf_single_core_down_20_mean_neg_neut_pxret21", "core_down", -1.0),
    ):
        if feature_id not in wanted_ids:
            continue
        y_raw: dict[str, float] = {}
        for code in sorted(scope):
            mean = window_mean([_stat(daily[d], code, stat) for d in window])
            if mean is not None:
                y_raw[code] = sign * mean
        residual = residualize(
            mad_winsorize(y_raw),
            utility_winsorize(pxret),
            min_obs=MIN_NEUTRAL_OBS,
        )
        out.extend(
            _row(
                event_dt=event_dt,
                code=code,
                feature_id=feature_id,
                value=value,
                knowledge_dt=knowledge_dt,
                pit_grade=pit_grade,
                computed_at=computed_at,
                run_id=run_id,
            )
            for code, value in sorted(residual.items())
        )
    return out


def load_daily_2b(
    repo: MinuteBarRepository,
    *,
    as_of: date,
    day: date,
    codes: Collection[str],
) -> dict[str, MinuteDay2b]:
    """读取 ``day`` 当日 ``codes`` 中股票的第二批日值。排除集从请求中减去，被排除的股票不在结果中。"""
    excluded = repo.excluded_codes(as_of=as_of, day=day)
    requested = sorted(code for code in codes if code not in excluded)
    if not requested:
        return {}
    table = repo.scan_window(
        as_of=as_of, start=day, end=day, codes=requested, columns=MINUTE_COLUMNS
    )
    return _day_2b(table.to_pylist(), day)


def pxret21(p_start: float | None, p_end: float | None) -> float | None:
    """``(p_end − p_start) / |p_start|``。任一端缺失或起点为 0 时缺失，与旧 SQL 的 ``NULLIF`` 一致。"""
    if p_start is None or p_end is None or p_start == 0:
        return None
    return (p_end - p_start) / abs(p_start)


def _day_2b(rows: Sequence[dict[str, Any]], day: date) -> dict[str, MinuteDay2b]:
    by_code: dict[str, list[tuple[datetime, float, float]]] = {}
    for row in rows:
        stamp = row["trade_time"]
        if stamp.date() != day:
            raise FeatureLookupError(f"分钟行的日期 {stamp.date()} 不等于 {day}")
        by_code.setdefault(str(row["ts_code"]), []).append(
            (stamp, float(row["close"]), float(row["vol"]))
        )
    out: dict[str, MinuteDay2b] = {}
    for code, items in by_code.items():
        items.sort(key=lambda item: item[0])
        if len({item[0] for item in items}) != len(items):
            raise FeatureLookupError(f"{code} 在 {day} 存在重复的 trade_time")
        corr, up, down = minute_day_2b(
            [item[1] for item in items],
            [item[2] for item in items],
        )
        out[code] = MinuteDay2b(corr_vrlaglarge=corr, core_up=up, core_down=down)
    return out


def _price_index(rows: Sequence[Any]) -> dict[tuple[str, date], float]:
    return {
        (row.wind_code, row.trade_dt): float(row.adj_close)
        for row in rows
        if row.adj_close is not None
    }


def _pxret_by_code(
    px: dict[tuple[str, date], float],
    scope: Collection[str],
    base_day: date,
    event_dt: date,
) -> dict[str, float]:
    out: dict[str, float] = {}
    for code in scope:
        value = pxret21(px.get((code, base_day)), px.get((code, event_dt)))
        if value is not None:
            out[code] = value
    return out


def _stat(day_map: dict[str, MinuteDay2b], code: str, stat: str) -> float | None:
    row = day_map.get(code)
    return None if row is None else getattr(row, stat)


def _row(
    *,
    event_dt: date,
    code: str,
    feature_id: str,
    value: float,
    knowledge_dt: date,
    pit_grade: str,
    computed_at: datetime,
    run_id: str,
) -> FeatureValue:
    return FeatureValue(
        event_dt=event_dt,
        asset_id=code,
        asset_class=_ASSET_CLASS,
        feature_id=feature_id,
        definition_version=DEFINITION_VERSION,
        param_hash=PARAM_HASHES[feature_id],
        value=value,
        knowledge_dt=knowledge_dt,
        pit_grade=pit_grade,
        computed_at=computed_at,
        run_id=run_id,
    )
