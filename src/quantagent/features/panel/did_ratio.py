"""把稳健股息率的截面输入收成因子长表行。不写文件，也不接受手填的可见日或 PIT 等级。

截面由调用方给出：``domain_by_day`` 是每个交易日的股票域（all_a 去掉当日 ST）。只有交易日才有截面。
血缘由实际读取的输入推导：每条输入记录按 ``ANN_DT``（市值按 T 当日）和契约等级进入
``derive_feature_lineage``，因此 ``knowledge_dt`` 是输入中最晚的公告日，``pit_grade`` 是输入中最差的等级。
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from quantagent.domain.feature_lineage import derive_feature_lineage
from quantagent.domain.feature_value import FeatureValue
from quantagent.domain.fundamental.types import (
    DividendRecord,
    IndicatorRecord,
    NetProfitRecord,
)
from quantagent.features.library.fundamental.did_ratio import (
    DEFINITION_VERSION,
    FEATURE_ID,
    PARAM_HASH,
    WINDOW_DAYS,
    DidRatioConflictError,
    did_ratio_realized_1,
    window_rows,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date, datetime
    from decimal import Decimal

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.derivative_indicator.types import MarketValue

_Record = DividendRecord | NetProfitRecord | IndicatorRecord


@dataclass(frozen=True, slots=True)
class DidRatioConflict:
    """某只股票某日因输入取值冲突而未产值。冲突不改口径，只跳过该股该日。"""

    event_dt: date
    asset_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class DidRatioBuild:
    values: tuple[FeatureValue, ...]
    conflicts: tuple[DidRatioConflict, ...]


def build_did_ratio_values(
    *,
    domain_by_day: Mapping[date, frozenset[str]],
    dividends: Sequence[DividendRecord],
    net_profits: Sequence[NetProfitRecord],
    indicators: Sequence[IndicatorRecord],
    market_values: Sequence[MarketValue],
    dividend_contract: VisibilityContract,
    income_contract: VisibilityContract,
    indicator_contract: VisibilityContract,
    market_contract: VisibilityContract,
    computed_at: datetime,
    run_id: str,
) -> DidRatioBuild:
    """逐交易日、逐股票计算。没有市值、没有窗口内利润表或财务指标行的股票不落行。

    同一报告期在最大公告日取值冲突的股票，本日不落行，并记入 ``conflicts``。
    """
    div_by_code = _group_by_asset(dividends)
    inc_by_code = _group_by_asset(net_profits)
    ind_by_code = _group_by_asset(indicators)
    mv_by_key: dict[tuple[date, str], Decimal | None] = {
        (row.trade_dt, row.wind_code): row.total_mv for row in market_values
    }
    div_grade = dividend_contract.visibility.grade
    inc_grade = income_contract.visibility.grade
    ind_grade = indicator_contract.visibility.grade
    mv_grade = market_contract.visibility.grade

    values: list[FeatureValue] = []
    conflicts: list[DidRatioConflict] = []
    for day in sorted(domain_by_day):
        lower = day - timedelta(days=WINDOW_DAYS)
        for code in sorted(domain_by_day[day]):
            market_value = mv_by_key.get((day, code))
            if market_value is None:
                continue
            divs = _window_slice(div_by_code.get(code), lower, day)
            incs = _window_slice(inc_by_code.get(code), lower, day)
            inds = _window_slice(ind_by_code.get(code), lower, day)
            try:
                value = did_ratio_realized_1(
                    as_of=day,
                    dividends=divs,
                    net_profits=incs,
                    indicators=inds,
                    market_value=market_value,
                )
            except DidRatioConflictError as exc:
                conflicts.append(DidRatioConflict(event_dt=day, asset_id=code, reason=str(exc)))
                continue
            if value is None:
                continue
            win = window_rows(as_of=day, dividends=divs, net_profits=incs, indicators=inds)
            # 血缘只取实际进入计算的输入（已裁剪到窗口与季末），市值按 T 当日可见。
            inputs = [
                *((row.ann_dt, div_grade) for row in win.dividends),
                *((row.ann_dt, inc_grade) for row in win.net_profits),
                *((row.ann_dt, ind_grade) for row in win.indicators),
                (day, mv_grade),
            ]
            knowledge_dt, pit_grade = derive_feature_lineage(inputs)
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
    return DidRatioBuild(values=tuple(values), conflicts=tuple(conflicts))


def _group_by_asset[Row: _Record](rows: Sequence[Row]) -> dict[str, _Sorted[Row]]:
    grouped: dict[str, list[Row]] = {}
    for row in rows:
        grouped.setdefault(row.asset_id, []).append(row)
    return {
        code: _Sorted(sorted(items, key=lambda item: item.ann_dt))
        for code, items in grouped.items()
    }


class _Sorted[Row: _Record]:
    """按 ``ANN_DT`` 升序的一只股票的行。用 bisect 取窗口，避免对全历史逐日线性扫描。"""

    __slots__ = ("_anns", "_rows")

    def __init__(self, rows: list[Row]) -> None:
        self._rows = rows
        self._anns = [row.ann_dt for row in rows]

    def between(self, lower: date, upper: date) -> tuple[Row, ...]:
        """``lower < ANN_DT <= upper`` 的行。"""
        lo = bisect_right(self._anns, lower)
        hi = bisect_right(self._anns, upper)
        return tuple(self._rows[lo:hi])


def _window_slice[Row: _Record](
    grouped: _Sorted[Row] | None,
    lower: date,
    upper: date,
) -> tuple[Row, ...]:
    if grouped is None:
        return ()
    return grouped.between(lower, upper)
