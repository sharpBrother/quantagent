"""``pf_single_tr_umr_1_mean_pos``。

旧仓 ``TR_UMR`` 在市场开市日上计算真实波幅相对 10 日均值的偏离，乘超额收益，
再按 60 日半衰期权重求和。Current-20 的消费窗口是 1、方向是 +1，长表直接存
这个原始值，不再套 mean、std、diff 或 pctchg。

v2 起，计算窗口内任一所需输入缺失即不产值，不再跳过缺失项求和（见 ``_weighted_umr``）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from quantagent.domain.errors import FeatureLookupError
from quantagent.domain.feature_lineage import derive_feature_lineage
from quantagent.platform.identity import digest_json

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.index_returns.types import IndexReturn
    from quantagent.domain.prices.types import DailyPrice

FEATURE_ID = "pf_single_tr_umr_1_mean_pos"
DEFINITION_VERSION = "v2"
RISK_WINDOW = 10
RET_WINDOW = 60
HALF_LIFE = 30
LOOKBACK = RET_WINDOW + RISK_WINDOW - 1
MEAN_WINDOW = 1
BENCHMARK = "000985.CSI"
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
class TrUmrValue:
    event_dt: date
    asset_id: str
    value: float
    knowledge_dt: date
    pit_grade: str


def reject_invalid_tr_umr_inputs(
    open_days: Sequence[date],
    prices: Sequence[DailyPrice],
    index_returns: Sequence[IndexReturn],
) -> None:
    """开市日、股票日、指数日重复，或指数不是中证全指时失败。"""
    seen_days: set[date] = set()
    for day in open_days:
        if day in seen_days:
            raise FeatureLookupError(f"开市日重复: {day.isoformat()}")
        seen_days.add(day)
    seen_index: set[date] = set()
    for index_row in index_returns:
        if index_row.wind_code != BENCHMARK:
            raise FeatureLookupError(f"指数代码不是 {BENCHMARK}: {index_row.wind_code}")
        if index_row.trade_dt in seen_index:
            raise FeatureLookupError(
                f"指数收益键重复: {index_row.wind_code} {index_row.trade_dt.isoformat()}"
            )
        seen_index.add(index_row.trade_dt)
    seen_prices: set[tuple[date, str]] = set()
    for price in prices:
        key = (price.trade_dt, price.wind_code)
        if key in seen_prices:
            raise FeatureLookupError(f"行情键重复: {price.wind_code} {price.trade_dt.isoformat()}")
        seen_prices.add(key)


def tr_umr_value(
    open_days: Sequence[date],
    prices: Sequence[DailyPrice],
    index_returns: Sequence[IndexReturn],
    *,
    price_contract: VisibilityContract,
    index_contract: VisibilityContract,
) -> TrUmrValue | None:
    """``open_days`` 是含截面日在内的开市日。不足 69 日则没有值。
    窗口内任一所需输入缺失（股票当日无行或字段为空，指数当日无收益）也没有值。

    不接受调用方传入 ``knowledge_dt`` 或 ``pit_grade``。
    """
    reject_invalid_tr_umr_inputs(open_days, prices, index_returns)
    if len(open_days) != LOOKBACK:
        return None
    codes = {row.wind_code for row in prices}
    if len(codes) > 1:
        raise FeatureLookupError("TR_UMR 一次只接受一只股票")
    ordered = tuple(sorted(open_days))
    tr, excess = _market_series(ordered, prices, index_returns)
    coef = _risk_coef(tr)
    # lookback = 60 + 10 - 1。前 9 日风险窗不满，加权只用最后 60 日。
    value = _weighted_umr(coef[-RET_WINDOW:], excess[-RET_WINDOW:])
    if value is None:
        return None
    asset_id = next(iter(codes), None)
    if asset_id is None:
        raise FeatureLookupError("TR_UMR 有值但没有股票行情")
    knowledge_dt, pit_grade = _lineage(
        ordered,
        prices,
        index_returns,
        price_contract=price_contract,
        index_contract=index_contract,
    )
    return TrUmrValue(
        event_dt=ordered[-1],
        asset_id=asset_id,
        value=value,
        knowledge_dt=knowledge_dt,
        pit_grade=pit_grade,
    )


def _market_series(
    open_days: Sequence[date],
    prices: Sequence[DailyPrice],
    index_returns: Sequence[IndexReturn],
) -> tuple[list[float], list[float]]:
    # 旧仓 lookback_dates 来自 trade_cal 的开市日，不是每只股票自己的打印日。
    # 股票在某个开市日没行时，TR 和超额都留空，不能用更早的打印顶上。
    # last_n_trading_days 取的是该股票最近 N 次打印，这个因子不能用它对齐。
    price_by_day = {row.trade_dt: row for row in prices}
    index_by_day = {row.trade_dt: row for row in index_returns}
    tr: list[float] = []
    excess: list[float] = []
    for day in open_days:
        row = price_by_day.get(day)
        tr.append(_true_range(row))
        excess.append(_excess(row, index_by_day.get(day)))
    return tr, excess


def _true_range(row: DailyPrice | None) -> float:
    if row is None:
        return math.nan
    high = row.adj_high
    low = row.adj_low
    preclose = row.adj_preclose
    if high is None or low is None or preclose is None or preclose == 0:
        return math.nan
    # 旧仓把复权价转成 float 后走 numpy。Decimal 的滚动均值对不上 pandas rolling。
    # 不用未复权高低价推导。
    high_f = float(high)
    low_f = float(low)
    pre_f = float(preclose)
    if not math.isfinite(pre_f) or pre_f == 0.0:
        return math.nan
    amplitude = max(high_f - low_f, abs(high_f - pre_f), abs(low_f - pre_f))
    value = amplitude / pre_f
    if not math.isfinite(value):
        return math.nan
    return value


def _excess(row: DailyPrice | None, index_row: IndexReturn | None) -> float:
    if row is None or index_row is None:
        return math.nan
    stock = row.pct_change
    benchmark = index_row.pct_change
    if stock is None or benchmark is None:
        return math.nan
    # 涨跌幅单位是百分数点，旧仓直接相减，不除以 100。
    value = float(stock) - float(benchmark)
    if not math.isfinite(value):
        return math.nan
    return value


def _risk_coef(values: Sequence[float]) -> list[float]:
    # pandas Series.rolling(10, min_periods=10).mean() - series。
    # 窗口里有限值不足 10 个就是 NaN。缺口不补 0，也不用前值。
    coef = [math.nan] * len(values)
    for end in range(RISK_WINDOW - 1, len(values)):
        window = values[end - RISK_WINDOW + 1 : end + 1]
        if any(not math.isfinite(item) for item in window):
            continue
        mean = float(np.mean(np.asarray(window, dtype=np.float64)))
        coef[end] = mean - window[-1]
    return coef


def _weighted_umr(risk_tail: Sequence[float], excess_tail: Sequence[float]) -> float | None:
    # 逐位复制旧仓 get_exp_weight。最新一天权重最大。
    window = RET_WINDOW
    half_life = HALF_LIFE
    exp_wt = np.asarray([0.5 ** (1 / half_life)] * window) ** np.arange(window)
    weights = exp_wt[::-1] / np.sum(exp_wt)
    products = (
        weights
        * np.asarray(risk_tail, dtype=np.float64)
        * np.asarray(excess_tail, dtype=np.float64)
    )
    # v1 用 nansum 跳过缺失乘积，分母仍是满权重，等于把缺失当 0 贡献，违反 AGENTS.md §7.5
    # （缺失就是缺失，不补 0）。负责人 2026-11-22 裁定 v2：60 天中任一天的风险系数或超额收益
    # 不是有限值，整个截面不产值。风险系数第 t 天由 tr[t-9..t] 算出，因此这 60 个风险系数
    # 用到的真实波幅正好覆盖 69 日窗口的全部输入。超额收益前 9 日不进入公式，缺失不影响结果。
    if not all(math.isfinite(item) for item in risk_tail) or not all(
        math.isfinite(item) for item in excess_tail
    ):
        return None
    total = float(np.sum(products))
    signed = float(SIGN) * total
    if not math.isfinite(signed):
        raise FeatureLookupError("TR_UMR 结果不是有限值")
    return signed


def _lineage(
    open_days: Sequence[date],
    prices: Sequence[DailyPrice],
    index_returns: Sequence[IndexReturn],
    *,
    price_contract: VisibilityContract,
    index_contract: VisibilityContract,
) -> tuple[date, str]:
    window = set(open_days)
    price_grade = price_contract.visibility.grade
    index_grade = index_contract.visibility.grade
    inputs = [(row.trade_dt, price_grade) for row in prices if row.trade_dt in window]
    inputs.extend((row.trade_dt, index_grade) for row in index_returns if row.trade_dt in window)
    return derive_feature_lineage(tuple(inputs))
