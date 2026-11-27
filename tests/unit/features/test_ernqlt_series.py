"""``ernqlt_series`` 逐股票装配层测试。对照基准是旧仓 pandas 矩阵语义的手工核算。

覆盖：跨表存量按报告期对齐（含错位防呆）、流量 TTM 的 NaN 传播、CFO/CFI skipna、
折旧插值链接入、数据不足时 descriptor 输入为 None。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from quantagent.domain.fundamental.types import FinancialSeriesRecord
from quantagent.features.library.fundamental.ernqlt_series import (
    assemble_ernqlt_inputs,
)

D = Decimal


def _rec(
    period: str,
    field: str,
    value: float | None,
    asset: str = "X",
) -> FinancialSeriesRecord:
    d = date(int(period[:4]), int(period[4:6]), int(period[6:8]))
    return FinancialSeriesRecord(
        asset_id=asset,
        report_period=d,
        ann_dt=d,
        values={field: (D(str(value)) if value is not None else None)},
    )


def _rows(recs: list[FinancialSeriesRecord]) -> dict[date, FinancialSeriesRecord]:
    return {r.report_period: r for r in recs}


def _continuous_balance(asset: str = "X") -> dict[date, FinancialSeriesRecord]:
    """连续 5 期资产负债表。TOT_ASSETS=1000+10i, TOT_LIAB=500+5i。"""
    periods = ["20220331", "20220630", "20220930", "20231231"[:4] + "1231", "20230331"]
    # 修正报告期：2022Q1..2023Q1
    periods = ["20220331", "20220630", "20220930", "20221231", "20230331"]
    recs = []
    for i, p in enumerate(periods):
        recs.append(
            FinancialSeriesRecord(
                asset_id=asset,
                report_period=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
                ann_dt=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
                values={"TOT_ASSETS": D(1000 + 10 * i), "TOT_LIAB": D(500 + 5 * i)},
            )
        )
    return _rows(recs)


@pytest.mark.unit
def test_noa_aligned_by_report_period() -> None:
    """同报告期对齐：资产负债表与现金流量表期集合相同时，NOA 逐期正确。"""
    periods = ["20220331", "20220630", "20220930", "20221231", "20230331"]
    balance = _continuous_balance()
    # 现金流量表 cash_end=100+5i，与 balance 同报告期。
    cf_recs = [
        FinancialSeriesRecord(
            asset_id="X",
            report_period=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
            ann_dt=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
            values={"CASH_CASH_EQU_END_PERIOD": D(100 + 5 * i)},
        )
        for i, p in enumerate(periods)
    ]
    cashflow = _rows(cf_recs)
    # 财务指标 interest_debt=50（同期）。
    ind_recs = [
        FinancialSeriesRecord(
            asset_id="X",
            report_period=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
            ann_dt=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
            values={"S_FA_INTERESTDEBT": D(50)},
        )
        for p in periods
    ]
    indicator = _rows(ind_recs)

    out = assemble_ernqlt_inputs(
        balance_rows=balance, cashflow_rows=cashflow, income_rows={}, indicator_rows=indicator
    )
    # 每期 noa = (ta - cash) - (liab - debt)
    # 第0期(2022Q1): (1000-100)-(500-50) = 900-450 = 450
    # 第4期(2023Q1): (1040-120)-(520-50) = 920-470 = 450
    assert len(out.noa_series) == 5
    assert out.noa_series[0] == D(450)
    assert out.noa_series[-1] == D(450)


@pytest.mark.unit
def test_noa_missing_period_in_cashflow_yields_none() -> None:
    """现金流量表缺某报告期 → 该期 NOA 为 None（跨表错位不会产生错值）。"""
    periods = ["20220331", "20220630", "20220930", "20221231", "20230331"]
    balance = _continuous_balance()
    # 现金流量表只有 4 期，缺最早 2022Q1。
    cf_periods = ["20220630", "20220930", "20221231", "20230331"]
    cf_recs = [
        FinancialSeriesRecord(
            asset_id="X",
            report_period=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
            ann_dt=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
            values={"CASH_CASH_EQU_END_PERIOD": D(100)},
        )
        for p in cf_periods
    ]
    cashflow = _rows(cf_recs)
    ind_recs = [
        FinancialSeriesRecord(
            asset_id="X",
            report_period=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
            ann_dt=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
            values={"S_FA_INTERESTDEBT": D(50)},
        )
        for p in periods
    ]
    indicator = _rows(ind_recs)

    out = assemble_ernqlt_inputs(
        balance_rows=balance, cashflow_rows=cashflow, income_rows={}, indicator_rows=indicator
    )
    # 并集轴最近5期：2022Q1..2023Q1。2022Q1 无 cashflow → 该期 NOA None。其余期有 cash=100。
    assert len(out.noa_series) == 5
    assert out.noa_series[0] is None  # 2022Q1 缺 cash_end
    # 2022Q2: (1010-100)-(505-50)=910-455=455
    assert out.noa_series[1] == D(455)


@pytest.mark.unit
def test_noa_interest_debt_missing_fills_zero() -> None:
    """带息债务缺失补 0，其余字段缺失则该期 None。"""
    periods = ["20220331", "20220630", "20220930", "20221231", "20230331"]
    balance = _continuous_balance()
    cf_recs = [
        FinancialSeriesRecord(
            asset_id="X",
            report_period=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
            ann_dt=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
            values={"CASH_CASH_EQU_END_PERIOD": D(100)},
        )
        for p in periods
    ]
    cashflow = _rows(cf_recs)
    # indicator 全部无 S_FA_INTERESTDEBT（字段缺失）。
    ind_recs = [
        FinancialSeriesRecord(
            asset_id="X",
            report_period=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
            ann_dt=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
            values={"S_FA_INTERESTDEBT": None},
        )
        for p in periods
    ]
    indicator = _rows(ind_recs)

    out = assemble_ernqlt_inputs(
        balance_rows=balance, cashflow_rows=cashflow, income_rows={}, indicator_rows=indicator
    )
    # debt 补0：第0期 (1000-100)-(500-0)=900-500=400
    assert out.noa_series[0] == D(400)


@pytest.mark.unit
def test_net_profit_ttm_rolling_nan_propagation() -> None:
    """净利润 TTM：满 4 期且无缺失才产值（rolling NaN 传播）。"""
    # 连续 4 期净利润累计：Q1=10,Q2累计30,Q3累计60,Q4累计100 → 单季 Q1=NaN(首期),20,30,40
    periods = ["20220331", "20220630", "20220930", "20221231"]
    cumulative = [10, 30, 60, 100]
    inc_recs = [
        FinancialSeriesRecord(
            asset_id="X",
            report_period=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
            ann_dt=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
            values={"NET_PROFIT_EXCL_MIN_INT_INC": D(c)},
        )
        for p, c in zip(periods, cumulative, strict=True)
    ]
    income = _rows(inc_recs)
    out = assemble_ernqlt_inputs(
        balance_rows={}, cashflow_rows={}, income_rows=income, indicator_rows={}
    )
    # 只有4期，第一期(2022Q1)单季 is_last=False → None → rolling(4) 窗口含 None → NaN → None
    assert out.net_profit_ttm is None


@pytest.mark.unit
def test_net_profit_ttm_value_when_full() -> None:
    """净利润 TTM 满 4 期且连续时产值。"""
    # 5 期连续，前4期构成有效 rolling。累计 Q1=10,Q2=30,Q3=60,Q4=100, 2023Q1=15
    periods = ["20220331", "20220630", "20220930", "20221231", "20230331"]
    cumulative = [10, 30, 60, 100, 15]
    inc_recs = [
        FinancialSeriesRecord(
            asset_id="X",
            report_period=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
            ann_dt=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
            values={"NET_PROFIT_EXCL_MIN_INT_INC": D(c)},
        )
        for p, c in zip(periods, cumulative, strict=True)
    ]
    income = _rows(inc_recs)
    out = assemble_ernqlt_inputs(
        balance_rows={}, cashflow_rows={}, income_rows=income, indicator_rows={}
    )
    # 单季: 2022Q1=None(首期), Q2=20,Q3=30,Q4=40, 2023Q1=15(累计值,因Q1用累计)
    # 最新 TTM = rolling(4) 最后一值 = sum(2023Q1 前4季窗口) = sum([Q2,Q3,Q4,2023Q1])? 不对——
    # rolling 是滑动窗口,最后一值对应 2023Q1 行 = sum(单季[idx-3..idx]) = sum([Q2,Q3,Q4,2023Q1])?
    # 单季序列索引: 0=2022Q1(None),1=Q2(20),2=Q3(30),3=Q4(40),4=2023Q1(15)
    # rolling(4) 在 idx=4: window=idx1..4 = [20,30,40,15] sum=105
    assert out.net_profit_ttm == D(105)


@pytest.mark.unit
def test_cfo_cfi_single_keeps_raw_for_skipna() -> None:
    """CFO/CFI 单季序列保留原始值（含 None），skipna 求和在 acf_descriptor 处理。"""
    periods = ["20220331", "20220630", "20220930", "20221231", "20230331"]
    cumulative = [10, 30, 60, 100, 15]
    cf_recs = [
        FinancialSeriesRecord(
            asset_id="X",
            report_period=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
            ann_dt=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
            values={
                "NET_CASH_FLOWS_OPER_ACT": D(c),
                "NET_CASH_FLOWS_INV_ACT": D(c * 2),
            },
        )
        for p, c in zip(periods, cumulative, strict=True)
    ]
    cashflow = _rows(cf_recs)
    out = assemble_ernqlt_inputs(
        balance_rows={}, cashflow_rows=cashflow, income_rows={}, indicator_rows={}
    )
    # CFO 单季最近4期 = idx1..4 = [20,30,40,15]（2023Q1=15因Q1用累计）
    assert len(out.cfo_single) == 4
    assert out.cfo_single == (D(20), D(30), D(40), D(15))
    assert out.cfi_single == (D(40), D(60), D(80), D(30))


@pytest.mark.unit
def test_total_assets_latest_is_latest_period() -> None:
    """分母最新报告期总资产。"""
    balance = _continuous_balance()
    out = assemble_ernqlt_inputs(
        balance_rows=balance, cashflow_rows={}, income_rows={}, indicator_rows={}
    )
    # 最新期 2023Q1 TOT_ASSETS=1000+10*4=1040
    assert out.total_assets_latest == D(1040)


@pytest.mark.unit
def test_empty_tables_yield_none_inputs() -> None:
    """空表 → 全部输入为 None/空序列，不报错。"""
    out = assemble_ernqlt_inputs(
        balance_rows={}, cashflow_rows={}, income_rows={}, indicator_rows={}
    )
    assert out.net_profit_ttm is None
    assert out.da_ttm is None
    assert out.total_assets_latest is None
    assert all(v is None for v in out.noa_series)
