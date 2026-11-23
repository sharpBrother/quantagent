"""宏观序列的领域身份与观测形状。

序列 ID 是领域语言，不带表名；到源表的映射在适配器里。新增序列先在这里登记，
适配器没有映射的序列读取时报错，不返回空结果。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, get_args

from quantagent.domain.errors import InvalidQueryError

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

# 单位全部是百分数（2.5 表示 2.5%）。
# cn_cgb_10y：中债国债到期收益率 10 年（旧仓 ERP 的无风险利率口径）。
# us_ust_10y：美国财政部公布的 10 年期名义国债收益率，按美国交易日。
# us_tips_10y：10 年期 TIPS 实际收益率（FRED DFII10），按 ALFRED 首发版本可见。
MacroSeriesId = Literal["cn_cgb_10y", "us_ust_10y", "us_tips_10y"]
MACRO_SERIES: frozenset[str] = frozenset(get_args(MacroSeriesId))


@dataclass(frozen=True, slots=True)
class MacroVersion:
    """源端一个观测的一个版本。

    无修订的源（日行情类）每个观测只有一个版本，``visible_from`` 就是业务日；
    有修订的源（ALFRED）按 ``[visible_from, visible_to]`` 闭区间生效，
    ``visible_to`` 为空表示仍是当前版本。
    """

    series_id: str
    observation_date: date
    value: Decimal | None
    visible_from: date
    visible_to: date | None


@dataclass(frozen=True, slots=True)
class MacroObservation:
    series_id: str
    observation_date: date
    # 缺失保持为空：源端给空值时不回退到更早的版本。
    value: Decimal | None
    # 所选版本的可见起始日，供下游推导 knowledge_dt，不接受调用方填写。
    knowledge_dt: date
    pit_grade: str


def normalize_series_ids(series_ids: tuple[str, ...]) -> tuple[str, ...] | None:
    """空列表表示调用方没有观察域，返回 None；未登记或重复的序列直接失败。"""
    if not series_ids:
        return None
    if len(set(series_ids)) != len(series_ids):
        raise InvalidQueryError("series_id 重复")
    unknown = sorted(set(series_ids) - MACRO_SERIES)
    if unknown:
        raise InvalidQueryError(f"未登记的宏观序列: {', '.join(unknown)}")
    return series_ids
