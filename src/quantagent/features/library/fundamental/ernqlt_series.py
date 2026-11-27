"""``barra_cne6_ernqlt`` 的逐股票季度序列装配：把财报原始行加工成 ABS/ACF descriptor 的直接输入。

本模块是 ``financial_series``（季度序列原语）与 ``ernqlt``（descriptor 纯函数）之间的装配层。
输入是**单只股票**的四张表已去重（keep=last）行，输出是 ``ErnqltInputs``——
ABS/ACF 两个 descriptor 计算所需的全部标的量。**纯函数、零存储依赖**，跨股票合成不在这里。

与旧仓 ``QUALITY.__init__`` + ``ERNQLT`` 的矩阵语义对应（已用 pandas 实证逐股票等效，
见 ``tests/unit/features/test_ernqlt_series.py`` 的对照）：

- pivot 的行 ``last_report_num`` 是**稠密序号**（0..n-1，按该股有数据的报告期排序），
  缺季不产生空洞行；``rolling(4)`` 逐列独立，列内时序就是该股财报时序。
  故矩阵 ``income_y.iloc[-1]`` ≡ 逐股票 ``rolling(4).sum()`` 最后一值（NaN 传播一致）。
- **跨表对齐偏差（忠实复现旧仓矩阵）**：旧仓 pivot 按各自表内的稠密序号对齐行，
  ``noa = (ta − cash) − (tl − td)`` 的逐行相减其实是**序号对齐、不是报告期对齐**。
  当资产负债表与现金流量表的报告期集合不同（如现金流量表缺早期季报）时，同一序号指向
  不同报告期，旧仓错位相减是缺陷。本模块**按报告期（date）对齐**各表存量序列——更严格、
  更符合"净经营资产同一报告期"的经济含义。数据充分（两表期集合相同）时与旧仓一致；
  数据不足时本仓该期 NOA 为空，进而 descriptor 为空，符合"数据不足则 descriptor 为空"裁定。
  差异登记见 ``docs/adr``（barra 迁移 ADR）。

流量 TTM 的两种求和口径（忠实复现旧仓并存语义，不可统一）：

- ``ni_ttm``/``da_ttm`` 用 ``rolling(4).sum()`` **NaN 传播**：满 4 期且窗口内无缺失才产值。
- ``cfo``/``cfi`` 用 ``tail(4).sum()`` **skipna**：忽略缺失季只对有数据的季求和，全缺失按 0。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from quantagent.features.library.fundamental.financial_series import (
    latest_value,
    rolling_ttm,
    sorted_periods,
    split_single_quarter,
)

if TYPE_CHECKING:
    from datetime import date

    from quantagent.domain.fundamental.types import FinancialSeriesRecord

# ERNQLT 回看报告期数（5 期存量 + rolling 暖机）。与旧仓 ``count=5*4+1`` 一致。
ERNQLT_COUNT = 5 * 4 + 1
# 流量 TTM 窗口（4 个季度）。
TTM_WINDOW = 4
# ABS 存量序列期数（5 期首尾差 = 近 4 季 NOA 变化）。
NOA_PERIODS = 5

# 字段名常量（Wind 源端列名，保持原文）。
F_TOT_ASSETS = "TOT_ASSETS"
F_TOT_LIAB = "TOT_LIAB"
F_CASH_END = "CASH_CASH_EQU_END_PERIOD"
F_INTEREST_DEBT = "S_FA_INTERESTDEBT"
F_NET_PROFIT = "NET_PROFIT_EXCL_MIN_INT_INC"
F_DA = "S_STM_IS"
F_CFO = "NET_CASH_FLOWS_OPER_ACT"
F_CFI = "NET_CASH_FLOWS_INV_ACT"

# 各表读取字段（adapter list_series 的 fields 参数）。只取 ERNQLT 需要的列，不多取。
BALANCE_FIELDS = (F_TOT_ASSETS, F_TOT_LIAB)
CASHFLOW_FIELDS = (F_CASH_END, F_CFO, F_CFI)
INCOME_FIELDS = (F_NET_PROFIT,)
INDICATOR_FIELDS = (F_INTEREST_DEBT, F_DA)


@dataclass(frozen=True, slots=True)
class ErnqltInputs:
    """单只股票在某一截面日的 ERNQLT 全部输入。金额单位元，比值无量纲。

    ``noa_series`` 是最近 ``NOA_PERIODS`` 期净经营资产（按报告期升序、最新在最后，
    逐期 ``(TOT_ASSETS − cash_end) − (TOT_LIAB − interest_debt)``，**已按报告期跨表对齐**）。
    ``interest_debt`` 缺失补 0（旧仓 ``fillna(0)``），其余三项任一缺失则该期 NOA 为 None。
    ``*_ttm`` 是 TTM 标量；``cfo_single``/``cfi_single`` 是最近 4 期单季序列（skipna 求和由
    ``acf_descriptor`` 处理）。任何一项为 None 都表示该部分数据不足，由 descriptor 判空。
    """

    noa_series: tuple[Decimal | None, ...]
    net_profit_ttm: Decimal | None
    da_ttm: Decimal | None
    cfo_single: tuple[Decimal | None, ...]
    cfi_single: tuple[Decimal | None, ...]
    total_assets_latest: Decimal | None


def assemble_ernqlt_inputs(
    *,
    balance_rows: dict[date, FinancialSeriesRecord],
    cashflow_rows: dict[date, FinancialSeriesRecord],
    income_rows: dict[date, FinancialSeriesRecord],
    indicator_rows: dict[date, FinancialSeriesRecord],
) -> ErnqltInputs:
    """把单只股票四张表的去重行装配成 ERNQLT 输入。

    四个 ``*_rows`` 都是 ``dedupe_keep_last`` 的结果（{report_period: 行}），键为报告期。
    各表独立做 tail(21)。流量字段先累计→单季拆分（折旧 ``S_STM_IS`` 走月度比例插值链）。
    **存量字段按报告期跨表对齐**取最近 5 期并集，逐期算 NOA——见模块 docstring 的对齐偏差说明。
    任何表为空或字段缺失，对应输出为 None（不补 0、不跨期填充，带息债务除外）。
    """
    noa_series = _aligned_noa_series(
        balance_rows=balance_rows,
        cashflow_rows=cashflow_rows,
        indicator_rows=indicator_rows,
    )

    # 净利润 TTM：累计→单季拆分后 rolling(4).sum()（NaN 传播，满4期才产值），取最新值。
    ni_single = [v for _, v in split_single_quarter(income_rows, F_NET_PROFIT, count=ERNQLT_COUNT)]
    net_profit_ttm = _latest_of_ttm(rolling_ttm(ni_single, window=TTM_WINDOW))

    # 折旧摊销 TTM：S_STM_IS 仅半年报+年报有数，缺失季走月度比例插值链（split_single_quarter 内建）。
    da_single = [v for _, v in split_single_quarter(indicator_rows, F_DA, count=ERNQLT_COUNT)]
    da_ttm = _latest_of_ttm(rolling_ttm(da_single, window=TTM_WINDOW))

    # CFO/CFI 单季序列（最近 4 期），求和口径是 skipna，由 acf_descriptor 处理——这里保留原始单季值。
    cfo_all = [v for _, v in split_single_quarter(cashflow_rows, F_CFO, count=ERNQLT_COUNT)]
    cfi_all = [v for _, v in split_single_quarter(cashflow_rows, F_CFI, count=ERNQLT_COUNT)]
    cfo_single = tuple(cfo_all[-TTM_WINDOW:])
    cfi_single = tuple(cfi_all[-TTM_WINDOW:])

    return ErnqltInputs(
        noa_series=noa_series,
        net_profit_ttm=net_profit_ttm,
        da_ttm=da_ttm,
        cfo_single=cfo_single,
        cfi_single=cfi_single,
        total_assets_latest=latest_value(balance_rows, F_TOT_ASSETS),
    )


def _aligned_noa_series(
    *,
    balance_rows: dict[date, FinancialSeriesRecord],
    cashflow_rows: dict[date, FinancialSeriesRecord],
    indicator_rows: dict[date, FinancialSeriesRecord],
) -> tuple[Decimal | None, ...]:
    """最近 5 期净经营资产序列，**按报告期跨表对齐**。

    报告期轴取三张表（资产负债表/现金流量表/财务指标表）tail(21) 后报告期的**并集**，
    升序取最近 ``NOA_PERIODS`` 期。逐期：

    - ``TOT_ASSETS``/``TOT_LIAB`` 来自资产负债表（同期）、``cash_end`` 来自现金流量表（同期）。
      三者任一缺失则该期 NOA 为 None（不补 0、不跨期填充）。
    - ``interest_debt`` 来自财务指标表（同期），缺失补 0（旧仓 ``fillna(0)``，仅此项补 0）。

    与旧仓按稠密序号对齐的差异见模块 docstring——本仓按报告期对齐更严格。
    """
    periods_union: set[date] = set()
    for rows in (balance_rows, cashflow_rows, indicator_rows):
        periods_union.update(sorted_periods(rows, count=ERNQLT_COUNT))
    axis = sorted(periods_union)[-NOA_PERIODS:]
    out: list[Decimal | None] = []
    for period in axis:
        ta = _field_at(balance_rows, period, F_TOT_ASSETS)
        cash = _field_at(cashflow_rows, period, F_CASH_END)
        liab = _field_at(balance_rows, period, F_TOT_LIAB)
        debt = _field_at(indicator_rows, period, F_INTEREST_DEBT)
        if ta is None or cash is None or liab is None:
            out.append(None)
            continue
        debt_val = debt if debt is not None else Decimal(0)
        out.append((ta - cash) - (liab - debt_val))
    return tuple(out)


def _field_at(rows: dict[date, FinancialSeriesRecord], period: date, field: str) -> Decimal | None:
    """某报告期某字段的值。该期无行或字段缺失返回 None。"""
    row = rows.get(period)
    if row is None:
        return None
    return row.values.get(field)


def _latest_of_ttm(ttm_series: list[Decimal | None]) -> Decimal | None:
    """TTM 序列最新（最后一个）值。空序列返回 None。"""
    if not ttm_series:
        return None
    return ttm_series[-1]
