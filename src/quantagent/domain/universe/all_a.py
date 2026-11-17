"""all_a 股票池：读取时计算，不物化。

成员 = 规则池 ∩ 当日"市值已观测"集合。规则池只看上市、退市、交易所与代码前缀；
市值已观测只看当日衍生指标行。两者都在 dt 当日求值，结果不落库。

``pit_grade`` 为 B 的原因：规则池的输入是 ``src_wind.ASHAREDESCRIPTION``，它是
当前态主数据，上市日与退市日只有最新值，没有"当时已知"的版本。因此即使 as_of
切片已经做了，上市/退市信息仍可能来自事后修订，不能评为 A。

市值已观测为什么要算：旧仓 ``alpha_factory/all_a_canonical_scene.py`` 的 canonical
分母是"当日同时有总市值与流通市值的观测域"。只按上市规则取池会把当日缺市值的
股票（多为长期停牌或临近退市）放进分母，换掉了约定的 observed domain（AGENTS.md §7.6）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from quantagent.domain.universe.member import UniverseMember

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Set as AbstractSet
    from datetime import date

ALL_A_UNIVERSE_ID = "all_a"
# 旧仓 ``LISTDATE < dt - 365 天``。换算成"上市满 366 天"，见 ``_listed_long_enough``。
ALL_A_MIN_LIST_DAYS = 365
ALL_A_PIT_GRADE = "B"
_BSE_EXCHANGE = "BSE"


@dataclass(frozen=True)
class ListingRow:
    """``ASHAREDESCRIPTION`` 的规则相关四列。日期已解析为 ``date``，空值为 ``None``。"""

    asset_id: str
    list_date: date | None
    delist_date: date | None
    exchange_market: str | None


def all_a_listed(listings: Iterable[ListingRow], *, dt: date) -> frozenset[str]:
    """dt 当日规则池的代码集合。只看上市、退市、交易所、代码前缀。"""
    return frozenset(row.asset_id for row in listings if _is_listed(row, dt=dt))


def all_a_members(
    listings: Iterable[ListingRow],
    *,
    dt: date,
    observed: AbstractSet[str],
) -> tuple[UniverseMember, ...]:
    """规则池 ∩ ``observed``，按代码升序。空结果返回空元组，空域报错由适配器负责。"""
    listed = all_a_listed(listings, dt=dt)
    codes = sorted(listed & set(observed))
    return tuple(
        UniverseMember(
            universe_id=ALL_A_UNIVERSE_ID,
            asset_id=code,
            valid_from=dt,
            valid_to=dt,
            member_weight=None,
            knowledge_dt=dt,
            pit_grade=ALL_A_PIT_GRADE,
        )
        for code in codes
    )


def _is_listed(row: ListingRow, *, dt: date) -> bool:
    if not _listed_long_enough(row.list_date, dt=dt):
        return False
    if not _not_delisted(row.delist_date, dt=dt):
        return False
    # 旧 SQL 写 ``!= 'BSE'``，对 NULL 不成立；这里显式把 None 也排除。
    if row.exchange_market is None or row.exchange_market == _BSE_EXCHANGE:
        return False
    # 以 A 开头的代码在旧仓 UniverseProvider 中被排除。
    return not row.asset_id.startswith("A")


def _listed_long_enough(list_date: date | None, *, dt: date) -> bool:
    # 旧仓条件 ``LISTDATE < dt - 365 天`` 等价于 ``dt >= list_date + 366 天``。
    # 上市当天与满 365 天那天都不是成员。
    if list_date is None:
        return False
    return dt >= list_date + timedelta(days=ALL_A_MIN_LIST_DAYS + 1)


def _not_delisted(delist_date: date | None, *, dt: date) -> bool:
    # 旧仓条件 ``DELISTDATE > dt``。退市日当天已不在池内，故要求 dt <= 退市日 - 1 天。
    if delist_date is None:
        return True
    return dt <= delist_date - timedelta(days=1)
