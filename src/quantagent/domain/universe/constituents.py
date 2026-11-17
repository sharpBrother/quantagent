"""指数与行业成分股票池。仓储只取行；区间命中与重叠检查在这里算。

universe_id 形如 ``<family>:<index_code>``，family 决定读哪张 Wind 成分表。
表名映射只在适配器里，这里只认 family 名。

``pit_grade`` 为 B 的原因：源表 ``AINDEXMEMBERS`` 等只有 ``S_CON_INDATE`` /
``S_CON_OUTDATE`` 生效区间，没有公告日或发布日。这里把 INDATE 当作 knowledge_dt，
只是近似，不能评为 A。

重叠报错的原因：wx2 在 2025-02 之后，000300.SH 下的 601058.SH 有 20250206 与
20250304 两条都未结束的区间。旧采集只按 OBJECT_ID 删除，没有处理 OPMODE=2 的残行，
同一天会被两行覆盖。这里不去重、不挑一条，直接报错，等源数据修正后再算。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from quantagent.domain.errors import InvalidQueryError
from quantagent.domain.universe.interval import interval_contains
from quantagent.domain.universe.member import UniverseMember

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

CONSTITUENT_FAMILIES: frozenset[str] = frozenset({"index", "citics1", "citics2", "citics3", "sw"})

# 只有生效区间、没有公告日，理由见模块文档。
CONSTITUENT_PIT_GRADE = "B"

_FAMILY_SEP = ":"


@dataclass(frozen=True)
class ConstituentRow:
    """成分表的一行。``in_date`` 为 ``S_CON_INDATE``，空值在计算前即报错。"""

    index_code: str
    asset_id: str
    in_date: date | None
    out_date: date | None


def parse_constituent_universe_id(universe_id: str) -> tuple[str, str]:
    """拆出 ``(family, index_code)``。非法格式、未知 family、空指数代码都报错。"""
    family, sep, index_code = universe_id.partition(_FAMILY_SEP)
    if not sep or family not in CONSTITUENT_FAMILIES:
        raise InvalidQueryError(f"不支持的 universe_id: {universe_id!r}")
    if not index_code or index_code != index_code.strip():
        raise InvalidQueryError(f"universe_id 缺少有效的指数代码: {universe_id!r}")
    return family, index_code


def constituent_members(
    rows: Iterable[ConstituentRow],
    *,
    universe_id: str,
    dt: date,
) -> tuple[UniverseMember, ...]:
    """dt 当日在池内的成分，按 asset_id 升序。无命中返回空元组，空域报错由适配器负责。

    只对本指数的行做检查。任一行 INDATE 为空即报错，不论它是否覆盖 dt，
    避免一条坏行在别的日期才暴露。
    """
    _family, index_code = parse_constituent_universe_id(universe_id)
    hits: list[UniverseMember] = []
    for row in rows:
        if row.index_code != index_code:
            continue
        if row.in_date is None:
            raise InvalidQueryError(f"S_CON_INDATE 为空: {index_code} {row.asset_id}")
        if not interval_contains(valid_from=row.in_date, valid_to=row.out_date, dt=dt):
            continue
        hits.append(
            UniverseMember(
                universe_id=universe_id,
                asset_id=row.asset_id,
                valid_from=row.in_date,
                valid_to=row.out_date,
                member_weight=None,
                knowledge_dt=row.in_date,
                pit_grade=CONSTITUENT_PIT_GRADE,
            )
        )
    _reject_overlap(hits, index_code=index_code, dt=dt)
    return tuple(sorted(hits, key=lambda member: member.asset_id))


def _reject_overlap(hits: list[UniverseMember], *, index_code: str, dt: date) -> None:
    # 同一 asset 在 dt 被两行覆盖时没有合法的单一结论，不挑选，直接报错。
    counts = Counter(member.asset_id for member in hits)
    duplicated = sorted(asset for asset, n in counts.items() if n > 1)
    if duplicated:
        raise InvalidQueryError(f"成分区间重叠 {index_code} {dt.isoformat()}: {duplicated}")
