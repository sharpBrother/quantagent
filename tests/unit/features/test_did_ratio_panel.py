"""稳健股息率面板：血缘等级、股票域、冲突跳过、窗口对观察日的可见性。零数据库、零文件。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.derivative_indicator.types import MarketValue
from quantagent.domain.fundamental.types import DividendRecord, IndicatorRecord, NetProfitRecord
from quantagent.features.panel.did_ratio import build_did_ratio_values

CODE = "000001.SZ"
OTHER = "600000.SH"
COMPUTED_AT = datetime(2026, 11, 25, tzinfo=UTC).replace(tzinfo=None)
RUN_ID = "test-run"


def _contract(
    dataset: str,
    *,
    rule: str,
    grade: str,
    field: str | None = None,
    event_field: str | None = None,
) -> VisibilityContract:
    visibility: dict[str, object] = {
        "rule": rule,
        "grade": grade,
        "rationale": "测试契约的可见性规则说明文字，长度足够通过校验",
    }
    if field is not None:
        visibility["field"] = field
    payload: dict[str, object] = {
        "dataset": dataset,
        "doc_ref": "docs/contracts/src-wind-first-batch.md",
        "temporal_kind": "period_with_revision" if event_field is None else "point_event",
        "visibility": visibility,
        "pit_recoverable": True,
    }
    if event_field is not None:
        payload["event_field"] = event_field
    else:
        payload["period_fields"] = ["REPORT_PERIOD"]
    return VisibilityContract.model_validate(payload)


def _contracts(*, dividend_grade: str = "B") -> dict[str, VisibilityContract]:
    return {
        "dividend": _contract(
            "src.wind.asharedividend", rule="source_field", grade=dividend_grade, field="ANN_DT"
        ),
        "income": _contract(
            "src.wind.ashareincome", rule="source_field", grade="A", field="ANN_DT"
        ),
        "indicator": _contract(
            "src.wind.asharefinancialindicator", rule="source_field", grade="A", field="ANN_DT"
        ),
        "market": _contract(
            "src.wind.ashareeodderivativeindicator",
            rule="same_day_close",
            grade="A",
            event_field="TRADE_DT",
        ),
    }


def _div(code: str, report: str, ann: str, tot: str) -> DividendRecord:
    return DividendRecord(
        asset_id=code,
        ann_dt=date.fromisoformat(ann),
        report_period=date.fromisoformat(report),
        tot_cash_dvd=Decimal(tot),
    )


def _inc(code: str, report: str, ann: str, profit: str) -> NetProfitRecord:
    return NetProfitRecord(
        asset_id=code,
        ann_dt=date.fromisoformat(ann),
        report_period=date.fromisoformat(report),
        net_profit_after_ded=Decimal(profit),
    )


def _ind(code: str, report: str, ann: str) -> IndicatorRecord:
    return IndicatorRecord(
        asset_id=code,
        ann_dt=date.fromisoformat(ann),
        report_period=date.fromisoformat(report),
    )


def _mv(code: str, day: str, mv: str) -> MarketValue:
    return MarketValue(
        trade_dt=date.fromisoformat(day),
        wind_code=code,
        total_mv=Decimal(mv),
    )


def _income_rows(code: str) -> list[NetProfitRecord]:
    # 最新 TTM 为 10，近 3 年有盈利年份；派息率与封顶的数值见单测 test_did_ratio.py。
    return [
        _inc(code, "2022-12-31", "2023-03-01", "100"),
        _inc(code, "2023-03-31", "2023-04-20", "5"),
        _inc(code, "2023-06-30", "2023-08-20", "10"),
        _inc(code, "2023-09-30", "2023-10-20", "15"),
        _inc(code, "2023-12-31", "2024-03-01", "10"),
    ]


def _indicator_rows(code: str) -> list[IndicatorRecord]:
    return [
        _ind(code, "2022-12-31", "2023-03-01"),
        _ind(code, "2023-12-31", "2024-03-01"),
    ]


def _dividend_rows(code: str) -> list[DividendRecord]:
    return [
        _div(code, "2022-12-31", "2023-03-01", "135"),
        _div(code, "2023-12-31", "2024-03-01", "0"),
    ]


def test_lineage_takes_worst_grade_and_latest_visible_date() -> None:
    contracts = _contracts(dividend_grade="B")
    day = date(2024, 6, 28)
    built = build_did_ratio_values(
        domain_by_day={day: frozenset({CODE})},
        dividends=_dividend_rows(CODE),
        net_profits=_income_rows(CODE),
        indicators=_indicator_rows(CODE),
        market_values=[_mv(CODE, "2024-06-28", "10000")],
        dividend_contract=contracts["dividend"],
        income_contract=contracts["income"],
        indicator_contract=contracts["indicator"],
        market_contract=contracts["market"],
        computed_at=COMPUTED_AT,
        run_id=RUN_ID,
    )
    assert len(built.values) == 1
    row = built.values[0]
    # 分红契约 B 是输入中最差的等级，结果必须是 B。
    assert row.pit_grade == "B"
    # 市值按 T 当日可见，knowledge_dt 不晚于 T。
    assert row.knowledge_dt == day
    assert row.event_dt == day
    assert row.asset_id == CODE
    assert row.asset_class == "stock"
    assert row.feature_id == "pf_single_stock_did_ratio_did_ratio_realized_1_1_mean_pos"
    assert row.definition_version == "v1"
    assert row.value > 0


def test_grade_follows_the_contract_not_a_hand_set_value() -> None:
    # 分红契约若被改为 A，结果等级随之变化。等级只从契约推导。
    contracts = _contracts(dividend_grade="A")
    day = date(2024, 6, 28)
    built = build_did_ratio_values(
        domain_by_day={day: frozenset({CODE})},
        dividends=_dividend_rows(CODE),
        net_profits=_income_rows(CODE),
        indicators=_indicator_rows(CODE),
        market_values=[_mv(CODE, "2024-06-28", "10000")],
        dividend_contract=contracts["dividend"],
        income_contract=contracts["income"],
        indicator_contract=contracts["indicator"],
        market_contract=contracts["market"],
        computed_at=COMPUTED_AT,
        run_id=RUN_ID,
    )
    assert built.values[0].pit_grade == "A"


def test_only_stocks_in_domain_produce_rows() -> None:
    # 股票域由调用方给出（all_a 去掉当日 ST）。域外的股票即使有数据也不产行。
    contracts = _contracts()
    day = date(2024, 6, 28)
    built = build_did_ratio_values(
        domain_by_day={day: frozenset({OTHER})},
        dividends=_dividend_rows(CODE),
        net_profits=_income_rows(CODE),
        indicators=_indicator_rows(CODE),
        market_values=[_mv(CODE, "2024-06-28", "10000")],
        dividend_contract=contracts["dividend"],
        income_contract=contracts["income"],
        indicator_contract=contracts["indicator"],
        market_contract=contracts["market"],
        computed_at=COMPUTED_AT,
        run_id=RUN_ID,
    )
    assert built.values == ()


def test_empty_latest_ttm_gives_no_row_and_is_not_a_conflict() -> None:
    # 裁定 2：最新 TTM 为空（2023-06-30 缺行，2023Q3 无法差分）时不落行；它不是同键冲突，不进 conflicts。
    contracts = _contracts()
    day = date(2024, 6, 28)
    incomes = [
        _inc(CODE, "2022-12-31", "2023-03-01", "100"),
        _inc(CODE, "2023-03-31", "2023-04-20", "5"),
        _inc(CODE, "2023-09-30", "2023-10-20", "15"),
        _inc(CODE, "2023-12-31", "2024-03-01", "10"),
        _inc(CODE, "2024-03-31", "2024-04-25", "3"),
    ]
    built = build_did_ratio_values(
        domain_by_day={day: frozenset({CODE})},
        dividends=_dividend_rows(CODE),
        net_profits=incomes,
        indicators=_indicator_rows(CODE),
        market_values=[_mv(CODE, "2024-06-28", "10000")],
        dividend_contract=contracts["dividend"],
        income_contract=contracts["income"],
        indicator_contract=contracts["indicator"],
        market_contract=contracts["market"],
        computed_at=COMPUTED_AT,
        run_id=RUN_ID,
    )
    assert built.values == ()
    assert built.conflicts == ()


def test_stock_without_market_value_on_that_day_is_skipped() -> None:
    contracts = _contracts()
    built = build_did_ratio_values(
        domain_by_day={date(2024, 6, 28): frozenset({CODE})},
        dividends=_dividend_rows(CODE),
        net_profits=_income_rows(CODE),
        indicators=_indicator_rows(CODE),
        market_values=[_mv(CODE, "2024-06-27", "10000")],
        dividend_contract=contracts["dividend"],
        income_contract=contracts["income"],
        indicator_contract=contracts["indicator"],
        market_contract=contracts["market"],
        computed_at=COMPUTED_AT,
        run_id=RUN_ID,
    )
    assert built.values == ()


def test_announcement_on_observation_day_is_visible_but_later_is_not() -> None:
    # 2022 年报在 2024-06-28 有一条修订（取值 0，成为最新公告）。
    # 公告日当天可见（ANN_DT <= T），因此 2024-06-28 取 0；2024-06-27 尚未公告，仍取 2022 年报原值。
    contracts = _contracts()
    revision = _div(CODE, "2022-12-31", "2024-06-28", "0")
    earlier_day = date(2024, 6, 27)
    on_day = date(2024, 6, 28)
    built = build_did_ratio_values(
        domain_by_day={earlier_day: frozenset({CODE}), on_day: frozenset({CODE})},
        dividends=[*_dividend_rows(CODE), revision],
        net_profits=_income_rows(CODE),
        indicators=_indicator_rows(CODE),
        market_values=[_mv(CODE, "2024-06-27", "10000"), _mv(CODE, "2024-06-28", "10000")],
        dividend_contract=contracts["dividend"],
        income_contract=contracts["income"],
        indicator_contract=contracts["indicator"],
        market_contract=contracts["market"],
        computed_at=COMPUTED_AT,
        run_id=RUN_ID,
    )
    by_day = {row.event_dt: row for row in built.values}
    assert by_day[earlier_day].value > 0
    assert by_day[on_day].value == 0
    assert by_day[on_day].knowledge_dt == on_day


def test_same_day_conflict_skips_only_that_stock() -> None:
    contracts = _contracts()
    day = date(2024, 6, 28)
    conflicting = [
        _div(OTHER, "2022-12-31", "2023-03-01", "10"),
        _div(OTHER, "2022-12-31", "2023-03-01", "135"),
    ]
    built = build_did_ratio_values(
        domain_by_day={day: frozenset({CODE, OTHER})},
        dividends=[*_dividend_rows(CODE), *conflicting],
        net_profits=_income_rows(CODE) + _income_rows(OTHER),
        indicators=_indicator_rows(CODE) + _indicator_rows(OTHER),
        market_values=[_mv(CODE, "2024-06-28", "10000"), _mv(OTHER, "2024-06-28", "10000")],
        dividend_contract=contracts["dividend"],
        income_contract=contracts["income"],
        indicator_contract=contracts["indicator"],
        market_contract=contracts["market"],
        computed_at=COMPUTED_AT,
        run_id=RUN_ID,
    )
    assert [row.asset_id for row in built.values] == [CODE]
    assert [(c.event_dt, c.asset_id) for c in built.conflicts] == [(day, OTHER)]
