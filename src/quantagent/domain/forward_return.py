"""``mart.forward_return``：行形状与纯计算。不读存储。

口径（负责人 2026-11-22 裁定）：

- 收益腿 ``open2open``。``event_dt`` 是信号日 T，因子在 T 收盘后形成，它不是可见日。
  区间起点 ``start_dt`` 是 T 之后的第一个开市日，终点 ``end_dt`` 是 T 之后第 h+1 个开市日。
  日历取 SSE 开市日历，不取个股自己的交易日。
- ``value = adj_open(end_dt) / adj_open(start_dt) - 1``。``adj_open`` 来自 ``S_DQ_ADJOPEN``，
  是后复权价，所以除权日的跳空被复权抹平，不会误计为收益。
- 端点任一停牌、缺行、``adj_open`` 缺失或非正或非有限，都不产行。缺失就是缺失，不补值。
- 停牌只看 ``trade_status_code == 0``，不看价格。停牌行的 ADJOPEN 取前收盘价，
  价格检查挡不住停牌。状态代码为空时无法证明端点未停牌，同样不产行。
- ``knowledge_dt`` 等于 ``end_dt``，即行情可见日。``pit_grade`` 由两端行情的
  ``(trade_dt, 价格契约等级)`` 经 ``derive_feature_lineage`` 推导，不接受手填。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from quantagent.domain.calendar import is_open, open_dates
from quantagent.domain.errors import CalendarLookupError, InvalidQueryError, PriceLookupError
from quantagent.domain.feature_lineage import derive_feature_lineage

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.calendar.types import CalendarDay
    from quantagent.domain.prices.types import DailyPrice

RETURN_LEG = "open2open"
RETURN_KIND = "total"
# total 收益没有基准。契约写的是字面值 none，不是把超额填成 0。
BENCHMARK_NONE = "none"
HORIZONS: tuple[str, ...] = ("1d", "5d", "10d", "20d")


@dataclass(frozen=True)
class ForwardReturn:
    asset_id: str
    event_dt: date
    horizon: str
    return_kind: str
    benchmark_id: str
    value: float
    end_dt: date
    knowledge_dt: date
    pit_grade: str
    return_leg: str
    start_dt: date


@dataclass(frozen=True)
class _Plan:
    """一个 (信号日, horizon) 的成熟区间。只有端点日期，价格在别处查。"""

    signal_dt: date
    start_dt: date
    end_dt: date
    horizon: str


def horizon_steps(horizon: str) -> int:
    """``5d`` 到 5。不在允许集合里的 horizon 直接拒绝，不猜测。"""
    if horizon not in HORIZONS:
        raise InvalidQueryError(f"不支持的 horizon: {horizon}，允许 {', '.join(HORIZONS)}")
    return int(horizon[:-1])


def forward_return_read_window(
    days: Sequence[CalendarDay],
    *,
    signal_dates: Sequence[date],
    horizons: Sequence[str] = HORIZONS,
    as_of: date,
) -> tuple[date, date] | None:
    """计算需要读取行情的闭区间 ``[最早信号日, 最晚成熟终点]``。没有成熟区间则返回 ``None``。
    调用方用它框定行情查询范围，避免为整段历史读全市场。
    """
    plans = _plan(days, signal_dates=signal_dates, horizons=horizons, as_of=as_of)
    if not plans:
        return None
    return min(p.signal_dt for p in plans), max(p.end_dt for p in plans)


def build_forward_returns(
    prices: Sequence[DailyPrice],
    days: Sequence[CalendarDay],
    *,
    signal_dates: Sequence[date],
    contract: VisibilityContract,
    as_of: date,
    horizons: Sequence[str] = HORIZONS,
) -> tuple[ForwardReturn, ...]:
    """用行情与日历算前瞻收益行。``as_of`` 之后的终点不产行。

    ``signal_dates`` 必须全是开市日，否则报错，不静默跳过。
    输出按 ``(asset_id, event_dt, horizon 步数)`` 排序，同一输入给出同一顺序。
    """
    plans = _plan(days, signal_dates=signal_dates, horizons=horizons, as_of=as_of)
    grade = contract.visibility.grade
    by_key: dict[tuple[str, date], DailyPrice] = {}
    for row in prices:
        key = (row.wind_code, row.trade_dt)
        if key in by_key:
            raise PriceLookupError(f"行情键重复: {row.wind_code} {row.trade_dt.isoformat()}")
        by_key[key] = row
    codes = sorted({row.wind_code for row in prices})
    out: list[ForwardReturn] = []
    for plan in plans:
        for code in codes:
            start_row = by_key.get((code, plan.start_dt))
            end_row = by_key.get((code, plan.end_dt))
            if start_row is None or end_row is None:
                continue
            start_open = _tradable_open(start_row)
            end_open = _tradable_open(end_row)
            if start_open is None or end_open is None:
                continue
            ratio = end_open / start_open - Decimal(1)
            knowledge_dt, pit_grade = derive_feature_lineage(
                ((start_row.trade_dt, grade), (end_row.trade_dt, grade))
            )
            out.append(
                ForwardReturn(
                    asset_id=code,
                    event_dt=plan.signal_dt,
                    horizon=plan.horizon,
                    return_kind=RETURN_KIND,
                    benchmark_id=BENCHMARK_NONE,
                    value=float(ratio),
                    end_dt=plan.end_dt,
                    knowledge_dt=knowledge_dt,
                    pit_grade=pit_grade,
                    return_leg=RETURN_LEG,
                    start_dt=plan.start_dt,
                )
            )
    out.sort(key=lambda r: (r.asset_id, r.event_dt, horizon_steps(r.horizon)))
    return tuple(out)


def _plan(
    days: Sequence[CalendarDay],
    *,
    signal_dates: Sequence[date],
    horizons: Sequence[str],
    as_of: date,
) -> tuple[_Plan, ...]:
    if not horizons:
        raise InvalidQueryError("horizons 为空")
    for horizon in horizons:
        horizon_steps(horizon)
    opens = open_dates(days)
    position = {dt: i for i, dt in enumerate(opens)}
    plans: list[_Plan] = []
    for signal_dt in sorted(set(signal_dates)):
        # is_open 对缺失或不可见的日历日同样报错：信号日必须确定是开市日。
        if not is_open(days, signal_dt):
            raise CalendarLookupError(f"信号日不是开市日: {signal_dt.isoformat()}")
        idx = position[signal_dt]
        if idx + 1 >= len(opens):
            continue
        start_dt = opens[idx + 1]
        if start_dt > as_of:
            continue
        for horizon in horizons:
            end_idx = idx + horizon_steps(horizon) + 1
            if end_idx >= len(opens):
                continue
            end_dt = opens[end_idx]
            if end_dt > as_of:
                continue
            plans.append(
                _Plan(signal_dt=signal_dt, start_dt=start_dt, end_dt=end_dt, horizon=horizon)
            )
    return tuple(plans)


def _tradable_open(row: DailyPrice) -> Decimal | None:
    """端点可用的复权开盘价。停牌、状态未知、价格缺失或非正，都返回 ``None``。"""
    if row.trade_status_code is None or row.trade_status_code == 0:
        return None
    price = row.adj_open
    if price is None or not price.is_finite() or price <= 0:
        return None
    return price
