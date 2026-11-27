"""行业归属仓储。只回答"某日各股票属于哪个中信一级行业"，不物化，也不暴露区间表。

与 ``UniverseRepository``（按行业指数查成员池）不同：本端口是**反向映射**——给定股票池，
逐股给出其归属的中信一级行业指数代码。用于 barra 风格因子 descriptor_process 的行业中位数填补。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date


class IndustryMapRepository(Protocol):
    def industry_map_at(self, *, as_of: date, dt: date) -> dict[str, str]:
        """``dt`` 当日 ``asset_id → 中信一级行业指数代码``（如 ``CI005005.WI``）的映射。

        覆盖 ``dt`` 当日有归属的全部股票。``as_of`` 决定可见性（成分生效区间按
        ``S_CON_INDATE <= dt <= S_CON_OUTDATE`` 切片，``knowledge_dt = INDATE``，grade B——
        源表无公告日，近似）。``dt > as_of`` 抛 ``InvalidQueryError``，不查库。
        一股同时命中多个一级行业（区间重叠）或 INDATE 为空 → 报错（fail-closed，不挑选）。
        无归属的股票**不在返回中**（调用方自行决定记 ``Unknown`` 或跳过）。
        不提供省略 ``as_of`` 的重载。
        """
        ...
