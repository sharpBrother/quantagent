"""稳健股息率 did_ratio_realized_1 的纯规则测试。零数据库、零文件。

数值按手工算出的结果写死，计算依据写在每个用例的注释里。
市值单位万元：mv_yuan = mv × 1e4。下面用 mv=10000，即 mv_yuan = 1e8。
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from quantagent.domain.errors import FeatureLookupError
from quantagent.domain.fundamental.types import DividendRecord, IndicatorRecord, NetProfitRecord
from quantagent.features.library.fundamental import did_ratio as dr

if TYPE_CHECKING:
    from collections.abc import Sequence

CODE = "000001.SZ"
AS_OF = date(2024, 6, 28)
MV = Decimal(10000)  # 万元，mv_yuan = 1e8
MV_YUAN = MV * Decimal(10000)


def _d(text: str) -> date:
    return date.fromisoformat(text)


def _div(report: str, ann: str, tot: str | None) -> DividendRecord:
    return DividendRecord(
        asset_id=CODE,
        ann_dt=_d(ann),
        report_period=_d(report),
        tot_cash_dvd=None if tot is None else Decimal(tot),
    )


def _inc(report: str, ann: str, profit: str | None) -> NetProfitRecord:
    return NetProfitRecord(
        asset_id=CODE,
        ann_dt=_d(ann),
        report_period=_d(report),
        net_profit_after_ded=None if profit is None else Decimal(profit),
    )


def _ind(report: str, ann: str) -> IndicatorRecord:
    return IndicatorRecord(asset_id=CODE, ann_dt=_d(ann), report_period=_d(report))


# 每个季末一条财务指标行，公告日取报告期后 60 天，窗口内都可见。
_INDICATORS = (
    _ind("2022-12-31", "2023-03-01"),
    _ind("2023-12-31", "2024-03-01"),
    _ind("2024-03-31", "2024-04-25"),
)


def _value(
    dividends: Sequence[DividendRecord],
    incomes: Sequence[NetProfitRecord],
    mv: Decimal | None = MV,
    indicators: Sequence[IndicatorRecord] = _INDICATORS,
    as_of: date = AS_OF,
) -> Decimal | None:
    return dr.did_ratio_realized_1(
        as_of=as_of,
        dividends=dividends,
        net_profits=incomes,
        indicators=indicators,
        market_value=mv,
    )


# 正常样本：近 3 年有盈利年份，派息率超过 80% 被封顶。
# 利润：2022 年报 100 元（同报告期 2022-06-30 等不影响年度值）、2023 年报 10 元。
# 2023 年报为最新行（年报 TTM = 10）。派息：2022 年报 135 元、2023 年报 0 元。
# 盈利年份 2022、2023，派息率 = 100 × 135 / (100 + 10) ≈ 122.7%，封顶 80。
# did_ratio_1 = 80 × 10 / 1e8 = 8e-6。
# realized = 100 × 135 / 1e8 / (36/12) = 4.5e-5，取 min 得 8e-6。
_NORMAL_DIVS = (
    _div("2022-12-31", "2023-03-01", "135"),
    _div("2023-12-31", "2024-03-01", "0"),
)
_NORMAL_INCS = (
    _inc("2022-03-31", "2022-04-20", "10"),
    _inc("2022-06-30", "2022-08-20", "20"),
    _inc("2022-09-30", "2022-10-20", "30"),
    _inc("2022-12-31", "2023-03-01", "100"),
    _inc("2023-03-31", "2023-04-20", "5"),
    _inc("2023-06-30", "2023-08-20", "10"),
    _inc("2023-09-30", "2023-10-20", "15"),
    _inc("2023-12-31", "2024-03-01", "10"),
)


def test_payout_cap_binds_when_uncapped_payout_exceeds_80_pct() -> None:
    got = _value(_NORMAL_DIVS, _NORMAL_INCS)
    assert got is not None
    assert got == Decimal(80) * Decimal(10) / MV_YUAN


def test_no_dividend_rows_in_window_gives_zero() -> None:
    # 裁定 A：窗口内没有分红记录，因子为 0。
    assert _value((), _NORMAL_INCS) == Decimal(0)


def test_dividends_older_than_three_year_cutoff_give_zero() -> None:
    # 裁定 A 的另一种情形：唯一的分红报告期 2019 年报早于 (lst 年 − 2) 年 1 月 1 日，旧代码走空分支。
    old = (_div("2019-12-31", "2020-03-01", "50"),)
    assert _value(old, _NORMAL_INCS) == Decimal(0)


def test_non_positive_latest_ttm_gives_zero() -> None:
    # 裁定 B：最新 TTM 扣非净利润 ≤ 0，did_ratio_1 = 0，因子 = min(realized, 0) = 0。
    incs = (*_NORMAL_INCS[:-1], _inc("2023-12-31", "2024-03-01", "-5"))
    assert _value(_NORMAL_DIVS, incs) == Decimal(0)


def test_no_profitable_year_gives_zero_not_eighty_pct_payout() -> None:
    # 裁定 C：近 3 年没有盈利年份，payout 为空，did_ratio_1 = 0。
    # 年度利润 2021、2022、2023 年均不为正；最新 TTM = Q2023Q2 + Q2023Q3 + Q2023Q4 + Q2024Q1 = 35 > 0。
    # 旧代码 min(80, NaN) = 80 会给出 80 × 35 / 1e8 > 0，这里必须为 0。
    incs = (
        _inc("2022-03-31", "2022-04-20", "-10"),
        _inc("2022-06-30", "2022-08-20", "-20"),
        _inc("2022-09-30", "2022-10-20", "-30"),
        _inc("2022-12-31", "2023-03-01", "-40"),
        _inc("2023-03-31", "2023-04-20", "-5"),
        _inc("2023-06-30", "2023-08-20", "-10"),
        _inc("2023-09-30", "2023-10-20", "-15"),
        _inc("2023-12-31", "2024-03-01", "-10"),
        _inc("2024-03-31", "2024-04-25", "40"),
    )
    divs = (
        _div("2022-12-31", "2023-03-01", "50"),
        _div("2023-12-31", "2024-03-01", "0"),
    )
    assert _value(divs, incs) == Decimal(0)


def test_missing_quarter_makes_ttm_empty_and_gives_no_value() -> None:
    # 裁定 2：最新 TTM 为空时不产值。旧代码退回 did_ratio_realized 且不封顶，这里必须为 None。
    # 最新行是 2024 年一季报（季报不是年报，TTM 需要单季差分）。2023-06-30 缺行，2023Q3 无法差分，
    # 最近四个单季中有空值，最新 TTM 为空。窗口内有分红，所以不走裁定 A 的 0。
    incs = (
        _inc("2022-03-31", "2022-04-20", "10"),
        _inc("2022-06-30", "2022-08-20", "20"),
        _inc("2022-09-30", "2022-10-20", "30"),
        _inc("2022-12-31", "2023-03-01", "100"),
        _inc("2023-03-31", "2023-04-20", "5"),
        _inc("2023-09-30", "2023-10-20", "15"),
        _inc("2023-12-31", "2024-03-01", "10"),
        _inc("2024-03-31", "2024-04-25", "3"),
    )
    assert _value(_NORMAL_DIVS, incs) is None


def test_latest_announcement_wins_among_revisions() -> None:
    # 同一报告期两条修订，取 ANN_DT 最大的一条（135），不取早的 10。
    divs = (
        _div("2022-12-31", "2023-03-01", "10"),
        _div("2022-12-31", "2023-06-01", "135"),
        _div("2023-12-31", "2024-03-01", "0"),
    )
    assert _value(divs, _NORMAL_INCS) == Decimal(80) * Decimal(10) / MV_YUAN


def test_latest_null_dividend_drops_the_report_after_dedupe() -> None:
    # 旧代码先去重再 dropna：最新一条为空，整个报告期被剔除，而不是回退到更早的非空值。
    divs = (
        _div("2022-12-31", "2023-03-01", "135"),
        _div("2022-12-31", "2023-06-01", None),
        _div("2023-12-31", "2024-03-01", "0"),
    )
    assert _value(divs, _NORMAL_INCS) == Decimal(0)


def test_same_announcement_with_identical_values_is_collapsed() -> None:
    divs = (
        _div("2022-12-31", "2023-03-01", "135"),
        _div("2022-12-31", "2023-03-01", "135"),
        _div("2023-12-31", "2024-03-01", "0"),
    )
    assert _value(divs, _NORMAL_INCS) == Decimal(80) * Decimal(10) / MV_YUAN


def test_same_announcement_with_different_values_is_a_conflict() -> None:
    divs = (
        _div("2022-12-31", "2023-03-01", "135"),
        _div("2022-12-31", "2023-03-01", "10"),
        _div("2023-12-31", "2024-03-01", "0"),
    )
    with pytest.raises(dr.DidRatioConflictError):
        _value(divs, _NORMAL_INCS)
    assert issubclass(dr.DidRatioConflictError, FeatureLookupError)


def test_window_is_open_at_start_and_closed_at_as_of() -> None:
    # 窗口为 (T − 1825 天, T]。起点当天不含，T 当天含。
    lower = AS_OF - timedelta(days=1825)
    on_lower = (_div("2022-12-31", lower.isoformat(), "135"),)
    just_inside = (_div("2022-12-31", (lower + timedelta(days=1)).isoformat(), "135"),)
    assert _value(on_lower, _NORMAL_INCS) == Decimal(0)
    assert _value(just_inside, _NORMAL_INCS) != Decimal(0)
    after = (_div("2022-12-31", (AS_OF + timedelta(days=1)).isoformat(), "135"),)
    assert _value(after, _NORMAL_INCS) == Decimal(0)


def test_non_quarter_report_period_is_ignored() -> None:
    # 报告期 2023-05-15 不是季末，不参与分红合计。
    divs = (*_NORMAL_DIVS, _div("2023-05-15", "2023-06-01", "9999"))
    assert _value(divs, _NORMAL_INCS) == Decimal(80) * Decimal(10) / MV_YUAN


def test_missing_inputs_do_not_produce_a_value() -> None:
    # 无利润表行、无财务指标行、无市值：不产值，返回 None。
    assert _value(_NORMAL_DIVS, ()) is None
    assert _value(_NORMAL_DIVS, _NORMAL_INCS, indicators=()) is None
    assert _value(_NORMAL_DIVS, _NORMAL_INCS, mv=None) is None


def test_non_positive_market_value_is_rejected() -> None:
    with pytest.raises(FeatureLookupError):
        _value(_NORMAL_DIVS, _NORMAL_INCS, mv=Decimal(0))


def test_mixed_asset_ids_are_rejected() -> None:
    other = DividendRecord(
        asset_id="600000.SH",
        ann_dt=_d("2023-03-01"),
        report_period=_d("2022-12-31"),
        tot_cash_dvd=Decimal(1),
    )
    with pytest.raises(FeatureLookupError):
        _value((*_NORMAL_DIVS, other), _NORMAL_INCS)


def test_param_hash_and_identity_are_stable() -> None:
    assert dr.FEATURE_ID == "pf_single_stock_did_ratio_did_ratio_realized_1_1_mean_pos"
    assert dr.DEFINITION_VERSION == "v1"
    assert dr.PARAM_HASH
    assert dr.PARAMS["window_days"] == 1825
    assert dr.PARAMS["statement_type"] == "408001000"
