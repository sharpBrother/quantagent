"""``barra_cne6_ernqlt``：Barra CNE6 盈利质量（Earnings Quality）风格的逐股票原始值计算。

复现旧仓 ``enhanced_optimizer/factors/exposure.py`` 的 ``QUALITY.ERNQLT``——2 个三级 descriptor
（ABS/ACF）等权合成。**本模块只算单股票的 descriptor 原始值**；跨股票的 descriptor_process
（去极值/行业中位填补/市值加权标准化）与 l3integrate 合成在 ``features.library.cross_section``
已就绪，由 panel 在全截面装配后调用。

输入数据结构（panel 用 ``financial_series`` 准备）：每只股票按报告期升序的字段序列。
所有金额单位元（与源端一致），比值无量纲。

旧仓矩阵语义 → 本模块逐股票语义的对应（关键，逐行核对）：

- ``balance_assets_q.tail(5)`` → 最近 5 期 ``TOT_ASSETS`` **存量**序列（不拆分）。
- ``noa = (ta − cash) − (tl − td)`` → 逐期：``(TOT_ASSETS − cash_end) − (TOT_LIAB − interest_debt)``。
  ``interest_debt`` 缺失补 0（旧仓 ``td_his.fillna(0)``，**仅带息债务补 0，其余字段缺失即缺失**）。
- ``delta_noa = noa.iloc[-1] − noa.iloc[-5]`` → 5 期序列**首尾差**（最新期 − 第 5 期前）。
  ``tail(5)`` 不足 5 期时旧仓 ``iloc[-5]`` 取的是现有最早行（非严格 5 期前）——本模块要求
  **恰好 5 期**，不足则 descriptor 为 None（见下"严格性差异"）。
- ``da_y.iloc[-1]`` → DA（折旧摊销 ``S_STM_IS`` 单季拆分后 rolling(4).sum()）TTM 最新值，
  **满 4 期且无缺失才产值**（rolling NaN 传播）。
- ``income_y.iloc[-1]`` → 净利润（``NET_PROFIT_EXCL_MIN_INT_INC``）TTM 最新值，同 rolling 严格。
- ``cfo_q.tail(4).sum()`` / ``cfi_q`` → CFO/CFI **单季**最近 4 期求和，**pandas sum skipna=True**
  ——忽略缺失季只对有数据的季求和（与 rolling 的 NaN 传播不同！旧仓两种求和口径并存，忠实复现）。
  不足 4 期也对现有期求和（tail 不足则 sum 现有行）。
- ``balance['TOT_ASSETS']`` → **最新报告期**总资产（标量分母），``tail(1)`` 即 keep=last 后最新期。

**严格性差异（与旧仓的偏差，登记）**：旧仓矩阵行是统一的 ``last_report_num``，``tail(5)``/``iloc[-5]``
在股票数据不足 5 期时取现有最早行（可能不足 4 季间隔）。本模块逐股票处理，要求 NOA 恰好 5 期
（对应 4 个季度间隔的 delta）；不足则 ABS 为 None。这更严格、更符合"4 季 NOA 变化"的本意，
且与"数据不足则 descriptor 为空"裁定一致。**影响面**：仅数据极少的股票（上市初期/长期停牌），
golden 对拍时若 wx2 这类股票有值而本仓 None，属可解释差异。
"""
from __future__ import annotations

from decimal import Decimal

# ABS 用 5 期存量算近 4 季 NOA 变化（5 期首尾差）。
_NOA_PERIODS = 5


def net_operating_assets(
    *,
    total_assets: Decimal | None,
    cash_end: Decimal | None,
    total_liab: Decimal | None,
    interest_debt: Decimal | None,
) -> Decimal | None:
    """单期净经营资产 ``noa = (TOT_ASSETS − cash_end) − (TOT_LIAB − interest_debt)``。

    ``interest_debt`` 缺失按 0 处理（旧仓 ``fillna(0)``）；其余三项任一缺失则整期 None。
    """
    if total_assets is None or cash_end is None or total_liab is None:
        return None
    debt = interest_debt if interest_debt is not None else Decimal(0)
    return (total_assets - cash_end) - (total_liab - debt)


def abs_descriptor(
    *,
    noa_series: list[Decimal | None],
    da_ttm: Decimal | None,
    total_assets_latest: Decimal | None,
) -> Decimal | None:
    """ABS（资产负债法应计）``= −(delta_noa − da) / TOT_ASSETS``。

    ``noa_series`` 是最近 5 期净经营资产（升序，最新在最后）。``delta_noa`` = 首尾差
    （最新期 − 最早期 = 近 4 季 NOA 变化）。要求恰好 5 期且首尾非空、``da_ttm`` 非空、
    分母非空非 0，否则 None。
    """
    if len(noa_series) != _NOA_PERIODS:
        return None
    latest = noa_series[-1]
    earliest = noa_series[0]
    if latest is None or earliest is None:
        return None
    if da_ttm is None or total_assets_latest is None or total_assets_latest == 0:
        return None
    delta_noa = latest - earliest
    return -(delta_noa - da_ttm) / total_assets_latest


def acf_descriptor(
    *,
    ni_ttm: Decimal | None,
    cfo_single: list[Decimal | None],
    cfi_single: list[Decimal | None],
    da_ttm: Decimal | None,
    total_assets_latest: Decimal | None,
) -> Decimal | None:
    """ACF（现金流法应计）``= −(ni − (cfo+cfi) + da) / TOT_ASSETS``。

    ``ni_ttm``/``da_ttm`` 是 TTM（rolling 严格，缺失即 None）。``cfo_single``/``cfi_single``
    是 CFO/CFI 单季序列（最近 4 期，升序），求和时 **skipna**（复现 pandas sum skipna=True）——
    忽略缺失季；但若**全部**缺失则 sum 为 0（pandas 空 sum=0），此处按 pandas 语义：全 None 求和得 0。
    注意 CFO/CFI 是单季值不是 TTM，``tail(4).sum()`` 即近 4 个单季之和 ≈ TTM。
    分母非空非 0 才产值。
    """
    if ni_ttm is None or da_ttm is None:
        return None
    if total_assets_latest is None or total_assets_latest == 0:
        return None
    cfo_sum = _skipna_sum(cfo_single)
    cfi_sum = _skipna_sum(cfi_single)
    accr = ni_ttm - (cfo_sum + cfi_sum) + da_ttm
    return -accr / total_assets_latest


def _skipna_sum(values: list[Decimal | None]) -> Decimal:
    """``pandas Series.sum()`` 默认 skipna=True：忽略 None。全 None 返回 0（pandas 空 sum=0）。"""
    total = Decimal(0)
    for v in values:
        if v is not None:
            total += v
    return total
