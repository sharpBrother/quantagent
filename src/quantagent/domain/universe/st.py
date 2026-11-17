"""ST 状态的当日判定。读取时计算，不物化。仓储只取行，区间判断与按代码去重在这里。

口径：``dt`` 当日为 ST，当且仅当存在一行满足 ``ENTRY_DT <= dt`` 且
（``REMOVE_DT`` 为空 或 ``dt < REMOVE_DT``）。左闭右开：戴帽当天算 ST，摘帽当天不算。

左闭右开取自旧仓 5 处当日判定的多数口径，全部作用于 wx2 ``dbo.ASHAREST``：
- ``strategy/growth_stock.py:367-371``、``strategy/growth_stock_2.py:287-291``：
  ``ENTRY_DT <= date AND (REMOVE_DT IS NULL OR REMOVE_DT > date)``
- ``factors/factor_etf.py:325-327``：pandas 写法，``date < REMOVE_DT`` 或 ``REMOVE_DT`` 为空
- ``factors/factor_fundamental.py:160-162``、``data/宽基指数配置策略2.py:322``：
  ``ENTRY_DT <= date AND (date < REMOVE_DT OR REMOVE_DT IS NULL)``

少数口径不采用，负责人 2026-11-17 已裁定：
- ``alpha_factory/data_gateway.py:1261`` 的 ``ENTRY_DT < trade_date``，把当日戴帽排除在外。
- ``core/universe_provider.py:174-175`` 的区间写法 ``REMOVE_DT >= from_date``，它是跨区间取行，
  不是当日判定。

PIT 等级 B：``ENTRY_DT`` 作为可见日。源表有 ``ANN_DT``，但旧仓没有一处使用它，本实现也不读。
不前视的理由：查询只使用 ``dt <= as_of``，且只取 ``ENTRY_DT <= dt`` 的行，因此参与判定的
戴帽日不晚于 ``as_of``。``REMOVE_DT`` 只用来判断 ``dt`` 之前是否已摘帽。源表没有 ``REMOVE_DT``
自身的发布时点字段，这里假定它在 ``dt`` 之前已可知。这是 B 级的残余风险，未在源表中核实。

同一代码的多行区间可以重叠，例如 ST 与 *ST 之间的类型切换，因此结果按代码去重，不报错。
结果为空是合法结果，返回空集合，不抛 ``EmptyDomainError``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from quantagent.domain.errors import InvalidQueryError

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

# ENTRY_DT 作可见日，等级 B。见模块注释。
ST_PIT_GRADE = "B"


@dataclass(frozen=True)
class StRow:
    """``ASHAREST`` 的一行。``remove_date`` 为 ``None`` 表示尚未摘帽。"""

    asset_id: str
    entry_date: date
    remove_date: date | None


def check_st_as_of(*, as_of: date, dt: date) -> None:
    """``dt`` 晚于 ``as_of`` 时不可见。调用方须在查库之前调用，失败时不得触库。"""
    if dt > as_of:
        raise InvalidQueryError(f"ST dt {dt.isoformat()} 晚于 as_of {as_of.isoformat()}")


def st_codes(rows: Iterable[StRow], *, dt: date) -> frozenset[str]:
    """返回 ``dt`` 当日为 ST 的代码集合。

    校验覆盖传入的每一行，包括 ``ENTRY_DT > dt`` 的行。这样同一组行在内存与 PG 两种
    适配器上得到同样的结果与同样的失败。
    """
    codes: set[str] = set()
    for row in rows:
        if not row.asset_id.strip():
            raise InvalidQueryError("ASHAREST 代码为空")
        if row.remove_date is not None and row.remove_date < row.entry_date:
            raise InvalidQueryError(f"REMOVE_DT 早于 ENTRY_DT: {row.asset_id}")
        if row.entry_date <= dt and (row.remove_date is None or dt < row.remove_date):
            codes.add(row.asset_id)
    return frozenset(codes)
