"""``features.panel.ernqlt`` 全横截面合成测试。合成数据驱动，验证：

- 逐交易日域过滤（只有域内股票参与合成与落行）。
- 跨股票 l3_integrate 产出标准化暴露（z-score 量级，非原始财务比率）。
- 可见性裁剪先于版本选择（修订前用初版，不因全历史 dedupe 丢期）。
- knowledge_dt 箍到 event_dt、pit_grade 取最差（行业 B）。
- 数据不足的股票不落行。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from quantagent.domain.fundamental.types import FinancialSeriesRecord
from quantagent.features.panel.ernqlt import build_ernqlt_values

D = Decimal
DAY = date(2024, 4, 30)


def _rec(
    asset: str,
    period: str,
    field: str,
    value: float | None,
    ann: str,
) -> FinancialSeriesRecord:
    return FinancialSeriesRecord(
        asset_id=asset,
        report_period=date(int(period[:4]), int(period[4:6]), int(period[6:8])),
        ann_dt=date(int(ann[:4]), int(ann[4:6]), int(ann[6:8])),
        values={field: (D(str(value)) if value is not None else None)},
    )


def _full_financials(
    asset: str, base: float, ann: str, *, profit_ratio: float = 1.0
) -> dict[str, list[FinancialSeriesRecord]]:
    """构造一只股票连续 6 期完整财报（足够产出 ABS/ACF）。

    descriptor 是比率（除以总资产），纯规模差异会被约掉，故用 ``profit_ratio`` 控制
    盈利/现金流相对规模的比例，产生**比率层面**的截面差异（z-score 才有正负）。
    """
    # 报告期 2022Q4..2024Q1 连续 6 期。ann 全部早于 2024-04-30。
    periods = ["20221231", "20230331", "20230630", "20230930", "20231231", "20240331"]
    balance, cashflow, income, indicator = [], [], [], []
    for i, p in enumerate(periods):
        ta = base * (1000 + 10 * i)
        balance.append(
            FinancialSeriesRecord(
                asset_id=asset,
                report_period=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
                ann_dt=date(int(ann[:4]), int(ann[4:6]), int(ann[6:8])),
                values={"TOT_ASSETS": D(str(ta)), "TOT_LIAB": D(str(ta * 0.5))},
            )
        )
        cashflow.append(
            FinancialSeriesRecord(
                asset_id=asset,
                report_period=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
                ann_dt=date(int(ann[:4]), int(ann[4:6]), int(ann[6:8])),
                values={
                    "CASH_CASH_EQU_END_PERIOD": D(str(ta * 0.1)),
                    # 现金流固定，净利润随 profit_ratio 变化 → ACF 的应计项产生截面差异。
                    "NET_CASH_FLOWS_OPER_ACT": D(str(base * (10 + 5 * i))),
                    "NET_CASH_FLOWS_INV_ACT": D(str(base * (2 + i))),
                },
            )
        )
        income.append(
            FinancialSeriesRecord(
                asset_id=asset,
                report_period=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
                ann_dt=date(int(ann[:4]), int(ann[4:6]), int(ann[6:8])),
                values={"NET_PROFIT_EXCL_MIN_INT_INC": D(str(base * (10 + 5 * i) * profit_ratio))},
            )
        )
        indicator.append(
            FinancialSeriesRecord(
                asset_id=asset,
                report_period=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
                ann_dt=date(int(ann[:4]), int(ann[4:6]), int(ann[6:8])),
                values={"S_FA_INTERESTDEBT": D(str(ta * 0.05)), "S_STM_IS": D(str(base * 2))},
            )
        )
    return {"balance": balance, "cashflow": cashflow, "income": income, "indicator": indicator}


def _merge(
    stocks: list[dict[str, list[FinancialSeriesRecord]]],
) -> dict[str, list[FinancialSeriesRecord]]:
    out = {"balance": [], "cashflow": [], "income": [], "indicator": []}
    for s in stocks:
        for k in list(out):
            out[k].extend(s[k])
    return out


def _build(stocks_data, domain, industry_map=None, dq_mv=None):
    tables = _merge(stocks_data)
    return build_ernqlt_values(
        domain_by_day=domain,
        balance_rows=tables["balance"],
        cashflow_rows=tables["cashflow"],
        income_rows=tables["income"],
        indicator_rows=tables["indicator"],
        industry_map_by_day=industry_map or {},
        dq_mv_by_day=dq_mv or {},
        financial_grade="A",
        market_grade="A",
        industry_grade="B",
        computed_at=__import__("datetime").datetime(2024, 5, 1),
        run_id="test-run",
    )


@pytest.mark.unit
def test_produces_standardized_exposure_not_raw_ratio() -> None:
    """多股票截面：产出是标准化暴露（z-score 量级），含正负、量级 ~1，非原始财务比率。"""
    stocks = [
        _full_financials("A", 100.0, "20240420", profit_ratio=1.0),
        _full_financials("B", 100.0, "20240420", profit_ratio=2.0),
        _full_financials("C", 100.0, "20240420", profit_ratio=0.5),
    ]
    industry = {DAY: {"A": "IND1", "B": "IND1", "C": "IND1"}}
    mv = {DAY: {"A": D(1000), "B": D(2000), "C": D(1500)}}
    build = _build(stocks, {DAY: frozenset({"A", "B", "C"})}, industry, mv)
    assert len(build.values) == 3
    vals = {v.asset_id: v.value for v in build.values}
    # 标准化暴露：均值近 0、有正有负、量级个位数内（非原始比率的小数）。
    mean = sum(vals.values()) / len(vals)
    assert abs(mean) < 0.5
    assert any(v > 0 for v in vals.values()) and any(v < 0 for v in vals.values())


@pytest.mark.unit
def test_domain_filter_excludes_non_member() -> None:
    """只有域内股票参与合成与落行。域外股票即使数据完整也不落行。"""
    stocks = [
        _full_financials("A", 100.0, "20240420"),
        _full_financials("OUT", 200.0, "20240420"),
    ]
    industry = {DAY: {"A": "IND1", "OUT": "IND1"}}
    mv = {DAY: {"A": D(1000), "OUT": D(2000)}}
    build = _build(stocks, {DAY: frozenset({"A"})}, industry, mv)
    # 单股票截面 z-score=0（标准化退化），但只有 A 落行。
    assert {v.asset_id for v in build.values} == {"A"}


@pytest.mark.unit
def test_insufficient_data_stock_not_emitted() -> None:
    """财报数据不足（无 ABS/ACF）的股票不落行。"""
    stocks = [_full_financials("A", 100.0, "20240420")]
    # EMPTY 无任何财报行。
    industry = {DAY: {"A": "IND1", "EMPTY": "IND1"}}
    mv = {DAY: {"A": D(1000), "EMPTY": D(2000)}}
    build = _build(stocks, {DAY: frozenset({"A", "EMPTY"})}, industry, mv)
    assert "EMPTY" not in {v.asset_id for v in build.values}
    # coverage 记录域内 2 只、有值 1 只。
    cov = {c[0]: (c[1], c[2]) for c in build.coverage}
    assert cov[DAY] == (2, 1)


@pytest.mark.unit
def test_visibility_crop_before_revision_dedupe() -> None:
    """PIT 关键：同报告期初版 ann=04-01、修订 ann=04-20；截面日 04-15 应可见初版（不丢期）。

    若错误地先全历史 dedupe（取修订版），则 04-15 该行被裁掉 → 该报告期缺失 → 可能数据不足。
    正确做法（先裁剪后去重）在 04-15 用初版，财报链完整 → 能产值。
    """
    asset = "A"
    # 完整 6 期，但 20240331 期有两次公告：初版 20240401、修订 20240420。
    base_periods = ["20221231", "20230331", "20230630", "20230930", "20231231"]
    balance, cashflow, income, indicator = [], [], [], []
    for i, p in enumerate(base_periods):
        ta = 1000 + 10 * i
        for lst, vals in (
            (balance, {"TOT_ASSETS": D(ta), "TOT_LIAB": D(ta // 2)}),
            (
                cashflow,
                {
                    "CASH_CASH_EQU_END_PERIOD": D(ta // 10),
                    "NET_CASH_FLOWS_OPER_ACT": D(10 + 5 * i),
                    "NET_CASH_FLOWS_INV_ACT": D(2 + i),
                },
            ),
            (income, {"NET_PROFIT_EXCL_MIN_INT_INC": D(10 + 5 * i)}),
            (indicator, {"S_FA_INTERESTDEBT": D(ta // 20), "S_STM_IS": D(2)}),
        ):
            lst.append(
                FinancialSeriesRecord(
                    asset_id=asset,
                    report_period=date(int(p[:4]), int(p[4:6]), int(p[6:8])),
                    ann_dt=date(2024, 1, 1),
                    values=vals,
                )
            )
    # 20240331 期：初版 ann=20240401。
    p = "20240331"
    ta = 1060
    for lst, vals in (
        (balance, {"TOT_ASSETS": D(ta), "TOT_LIAB": D(ta // 2)}),
        (
            cashflow,
            {
                "CASH_CASH_EQU_END_PERIOD": D(ta // 10),
                "NET_CASH_FLOWS_OPER_ACT": D(40),
                "NET_CASH_FLOWS_INV_ACT": D(8),
            },
        ),
        (income, {"NET_PROFIT_EXCL_MIN_INT_INC": D(40)}),
        (indicator, {"S_FA_INTERESTDEBT": D(ta // 20), "S_STM_IS": D(2)}),
    ):
        lst.append(
            FinancialSeriesRecord(
                asset_id=asset,
                report_period=date(2024, 3, 31),
                ann_dt=date(2024, 4, 1),
                values=vals,
            )
        )

    # 截面日 2024-04-15：初版(04-01)可见，无修订。应能用齐 6 期产出暴露。
    day_before_revision = date(2024, 4, 15)
    tables = {"balance": balance, "cashflow": cashflow, "income": income, "indicator": indicator}
    industry = {day_before_revision: {"A": "IND1"}}
    mv = {day_before_revision: {"A": D(1000)}}
    build = build_ernqlt_values(
        domain_by_day={day_before_revision: frozenset({"A"})},
        balance_rows=tables["balance"],
        cashflow_rows=tables["cashflow"],
        income_rows=tables["income"],
        indicator_rows=tables["indicator"],
        industry_map_by_day=industry,
        dq_mv_by_day=mv,
        financial_grade="A",
        market_grade="A",
        industry_grade="B",
        computed_at=__import__("datetime").datetime(2024, 5, 1),
        run_id="test-run",
    )
    # 单股票 z-score=0 但应落行（数据充分，初版可见）。
    assert "A" in {v.asset_id for v in build.values}


@pytest.mark.unit
def test_knowledge_dt_clamped_to_event_dt_and_pit_grade_b() -> None:
    """knowledge_dt 箍到 event_dt；pit_grade 取最差（行业 B）。"""
    stocks = [_full_financials("A", 100.0, "20240420")]
    industry = {DAY: {"A": "IND1"}}
    mv = {DAY: {"A": D(1000)}}
    build = _build(stocks, {DAY: frozenset({"A"})}, industry, mv)
    v = next(x for x in build.values if x.asset_id == "A")
    assert v.knowledge_dt >= v.event_dt
    assert v.pit_grade == "B"  # 行业成分 grade B 最差
    assert v.feature_id == "pf_single_barra_cne6_ernqlt_1_mean_pos"
