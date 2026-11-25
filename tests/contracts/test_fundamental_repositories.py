"""财报与分红窄端口契约：ANN_DT 截止、闭区间起点、代码与报表类型过滤、空结果。

内存实现与 PostgreSQL 实现遵循同一套规则；PostgreSQL 侧由 integration 测试覆盖。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from quantagent.adapters.memory.fundamental import (
    MemoryDividendRepository,
    MemoryFinancialIndicatorRepository,
    MemoryNetProfitRepository,
)
from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.errors import InvalidQueryError
from quantagent.domain.fundamental.types import DividendRecord, IndicatorRecord, NetProfitRecord

CODE = "000001.SZ"
OTHER = "600000.SH"
STATEMENT = "408001000"


def _contract(dataset: str) -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": dataset,
            "doc_ref": "docs/contracts/src-wind-first-batch.md",
            "temporal_kind": "period_with_revision",
            "period_fields": ["REPORT_PERIOD"],
            "visibility": {
                "rule": "source_field",
                "field": "ANN_DT",
                "grade": "A",
                "rationale": "契约测试用的财报公告日规则说明文字，长度足够通过校验",
            },
            "pit_recoverable": True,
        }
    )


def _d(text: str) -> date:
    return date.fromisoformat(text)


def _div(code: str, ann: str, report: str, tot: str) -> DividendRecord:
    return DividendRecord(
        asset_id=code, ann_dt=_d(ann), report_period=_d(report), tot_cash_dvd=Decimal(tot)
    )


def _inc(code: str, ann: str, report: str, profit: str | None) -> NetProfitRecord:
    return NetProfitRecord(
        asset_id=code,
        ann_dt=_d(ann),
        report_period=_d(report),
        net_profit_after_ded=None if profit is None else Decimal(profit),
    )


def _ind(code: str, ann: str, report: str) -> IndicatorRecord:
    return IndicatorRecord(asset_id=code, ann_dt=_d(ann), report_period=_d(report))


@pytest.mark.contracts
def test_dividend_visibility_closed_at_as_of_and_closed_interval_on_start() -> None:
    repo = MemoryDividendRepository(
        [
            _div(CODE, "2024-03-01", "2023-12-31", "10"),
            _div(CODE, "2024-06-28", "2023-12-31", "20"),
            _div(CODE, "2024-06-29", "2024-03-31", "30"),
        ],
        contract=_contract("src.wind.asharedividend"),
    )
    rows = repo.list_dividends(
        as_of=_d("2024-06-28"),
        start=_d("2024-03-01"),
        end=_d("2024-12-31"),
        wind_codes=(CODE,),
    )
    # 起点与截止都是闭区间：2024-03-01 与 2024-06-28 当天的公告都可见；2024-06-29 不可见。
    assert [(row.ann_dt, row.tot_cash_dvd) for row in rows] == [
        (_d("2024-03-01"), Decimal(10)),
        (_d("2024-06-28"), Decimal(20)),
    ]


@pytest.mark.contracts
def test_codes_and_statement_filters_apply() -> None:
    incomes = MemoryNetProfitRepository(
        {
            STATEMENT: [
                _inc(CODE, "2024-04-20", "2024-03-31", "5"),
                _inc(OTHER, "2024-04-20", "2024-03-31", "6"),
            ],
            "408002000": [_inc(CODE, "2024-04-20", "2024-03-31", "999")],
        },
        contract=_contract("src.wind.ashareincome"),
    )
    rows = incomes.list_net_profits(
        as_of=_d("2024-06-28"),
        start=_d("2024-01-01"),
        end=_d("2024-06-28"),
        statement_type=STATEMENT,
        wind_codes=(CODE,),
    )
    assert [(row.asset_id, row.net_profit_after_ded) for row in rows] == [(CODE, Decimal(5))]


@pytest.mark.contracts
def test_null_profit_is_kept_as_null_not_dropped() -> None:
    incomes = MemoryNetProfitRepository(
        {STATEMENT: [_inc(CODE, "2024-04-20", "2024-03-31", None)]},
        contract=_contract("src.wind.ashareincome"),
    )
    rows = incomes.list_net_profits(
        as_of=_d("2024-06-28"),
        start=_d("2024-01-01"),
        end=_d("2024-06-28"),
        statement_type=STATEMENT,
        wind_codes=(CODE,),
    )
    assert len(rows) == 1
    assert rows[0].net_profit_after_ded is None


@pytest.mark.contracts
def test_indicator_rows_hidden_before_announcement_and_empty_inputs_return_nothing() -> None:
    repo = MemoryFinancialIndicatorRepository(
        [_ind(CODE, "2024-07-01", "2024-03-31")],
        contract=_contract("src.wind.asharefinancialindicator"),
    )
    assert (
        repo.list_indicator_rows(
            as_of=_d("2024-06-28"),
            start=_d("2024-01-01"),
            end=_d("2024-12-31"),
            wind_codes=(CODE,),
        )
        == ()
    )
    assert (
        repo.list_indicator_rows(
            as_of=_d("2024-12-31"),
            start=_d("2024-01-01"),
            end=_d("2024-12-31"),
            wind_codes=(),
        )
        == ()
    )


@pytest.mark.contracts
def test_reversed_window_is_rejected() -> None:
    repo = MemoryDividendRepository([], contract=_contract("src.wind.asharedividend"))
    with pytest.raises(InvalidQueryError):
        repo.list_dividends(
            as_of=_d("2024-06-28"),
            start=_d("2024-06-28"),
            end=_d("2024-06-01"),
            wind_codes=(CODE,),
        )


@pytest.mark.contracts
def test_blank_statement_type_is_rejected() -> None:
    repo = MemoryNetProfitRepository({}, contract=_contract("src.wind.ashareincome"))
    with pytest.raises(InvalidQueryError):
        repo.list_net_profits(
            as_of=_d("2024-06-28"),
            start=_d("2024-01-01"),
            end=_d("2024-06-28"),
            statement_type=" ",
            wind_codes=(CODE,),
        )
