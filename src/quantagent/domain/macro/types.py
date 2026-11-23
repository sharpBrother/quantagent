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

# 除特别注明外单位是百分数（2.5 表示 2.5%；CPI 同比 2.5 表示上涨 2.5%）。
# cn_cgb_10y：中债国债到期收益率 10 年（旧仓 ERP 的无风险利率口径）。
# us_ust_10y：美国财政部公布的 10 年期名义国债收益率，按美国交易日，严格早于 as_of 可见。
# us_tips_10y：10 年期 TIPS 实际收益率（FRED DFII10），按 ALFRED 首发版本可见。
# cn_cpi_yoy：中国 CPI 同比（OECD MEI，FRED CPALTT01CNM659N），月频，观测日是月初。
#   ALFRED 版本从 2013-06 起，源端停在 2025-04；更早或更晚的月份按 as_of 不可见或缺失。
# cn_cpi_yoy_nbs：国家统计局 CPI 当期同比（聚源 C_ED_MacroIndicatorData 指标 110255493），
#   月频，观测日是月末（EndDate）；按 InfoPublDate 的日期当天可见。发布日从 2007-02 起，
#   更早月份不可见；源镜像数值为当前版本。
# cn_ppi_yoy_nbs：国家统计局 PPI 当期同比（聚源 C_ED_MacroIndicatorData 指标 110002644），
#   月频，观测日是月末（EndDate）；源端口径是“上年同月=100”，读取时减 100 转成同比
#   百分数。按 InfoPublDate 的日期当天可见，发布日从 2007-02 起。
# cn_cpi_nonfood_yoy_nbs：国家统计局 CPI 非食品当期同比（聚源指标 191001482），
#   口径与 cn_cpi_yoy_nbs 相同：月频，观测日是月末，按 InfoPublDate 日期当天可见。
# cn_ibo_7d：银行间同业拆借加权利率 7 天（聚源指标 601230002），日频，百分数，
#   观测日即交易日，按发布当天可见。
# cn_usdcny_fix：美元兑人民币中间价（聚源指标 110253785），日频，
#   **单位是人民币每美元，不是百分数**；按发布当天可见。
# de_bund_10y、jp_jgb_10y：德国、日本 10 年期国债收益率（OECD MEI 月均，FRED
#   IRLTLT01DEM156N、IRLTLT01JPM156N），观测日是月初，ALFRED 版本从 2013-06 起。
MacroSeriesId = Literal[
    "cn_cgb_10y",
    "us_ust_10y",
    "us_tips_10y",
    "cn_cpi_yoy",
    "cn_cpi_yoy_nbs",
    "cn_ppi_yoy_nbs",
    "cn_cpi_nonfood_yoy_nbs",
    "cn_ibo_7d",
    "cn_usdcny_fix",
    "de_bund_10y",
    "jp_jgb_10y",
]
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
