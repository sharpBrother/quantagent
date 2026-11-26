"""财报季度序列处理纯函数测试。对照基准是旧仓 pandas ``_add_quarter_col`` / ``rolling(4).sum()``。

覆盖：keep=last 去重、tail(count)、累计→单季拆分（含 is_last 连续性校验、Q1 第一期为 None）、
折旧摊销月度比例插值链、rolling TTM 的满4期+NaN传播。数值与 pandas 复现版逐位对照。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from quantagent.domain.fundamental.types import FinancialSeriesRecord
from quantagent.features.library.fundamental.financial_series import (
    dedupe_keep_last,
    get_last_period,
    latest_value,
    rolling_ttm,
    sorted_periods,
    split_single_quarter,
)


def _rec(
    period: str,
    field: str,
    value: float | None,
    ann: str | None = None,
    asset: str = "X",
) -> FinancialSeriesRecord:
    d = date(int(period[:4]), int(period[4:6]), int(period[6:8]))
    a = date(int(ann[:4]), int(ann[4:6]), int(ann[6:8])) if ann else d
    return FinancialSeriesRecord(
        asset_id=asset,
        report_period=d,
        ann_dt=a,
        values={field: (Decimal(str(value)) if value is not None else None)},
    )


def _split(periods_vals: list[tuple[str, float | None]], field: str) -> dict[str, float | None]:
    recs = tuple(_rec(p, field, v) for p, v in periods_vals)
    dm = dedupe_keep_last(recs)
    return {
        p.strftime("%Y%m%d"): (float(v) if v is not None else None)
        for p, v in split_single_quarter(dm["X"], field, count=21)
    }


@pytest.mark.unit
def test_get_last_period() -> None:
    assert get_last_period(date(2024, 3, 31)) == date(2023, 12, 31)
    assert get_last_period(date(2024, 6, 30)) == date(2024, 3, 31)
    assert get_last_period(date(2024, 9, 30)) == date(2024, 6, 30)
    assert get_last_period(date(2024, 12, 31)) == date(2024, 9, 30)
    assert get_last_period(date(2024, 5, 15)) is None  # 非季末


@pytest.mark.unit
def test_dedupe_keep_last_takes_latest_ann_dt() -> None:
    # 同报告期两次公告，keep=last 取 ann_dt 大的。
    old = _rec("20240331", "NP", 10.0, ann="20240420")
    new = _rec("20240331", "NP", 11.0, ann="20240428")
    dm = dedupe_keep_last((old, new))
    assert dm["X"][date(2024, 3, 31)].values["NP"] == Decimal("11.0")
    # 顺序无关（先新后旧仍取新）
    dm2 = dedupe_keep_last((new, old))
    assert dm2["X"][date(2024, 3, 31)].values["NP"] == Decimal("11.0")


@pytest.mark.unit
def test_sorted_periods_tail_count() -> None:
    recs = tuple(_rec(p, "NP", 1.0) for p in ["20230331", "20230630", "20230930", "20231231"])
    dm = dedupe_keep_last(recs)
    assert [p.strftime("%Y%m%d") for p in sorted_periods(dm["X"], count=2)] == ["20230930", "20231231"]
    # count 超过实际期数则全取
    assert len(sorted_periods(dm["X"], count=21)) == 4


@pytest.mark.unit
def test_split_continuous_flow() -> None:
    # 连续流量：累计 [10,30,60,100] → 单季 [None(Q1首期),20,30,40]。第一期 is_last=False → None。
    out = _split(
        [("20230331", 10.0), ("20230630", 30.0), ("20230930", 60.0), ("20231231", 100.0)],
        "NP",
    )
    assert out["20230331"] is None  # 序列第一期永远 None
    assert out["20230630"] == pytest.approx(20.0)
    assert out["20230930"] == pytest.approx(30.0)
    assert out["20231231"] == pytest.approx(40.0)


@pytest.mark.unit
def test_split_q1_with_continuous_prev_year_end() -> None:
    # Q1 有连续上期（上年报）→ 用累计值本身。
    out = _split([("20221231", 100.0), ("20230331", 10.0), ("20230630", 30.0)], "NP")
    assert out["20221231"] is None  # 第一期
    assert out["20230331"] == pytest.approx(10.0)  # Q1 = 累计
    assert out["20230630"] == pytest.approx(20.0)  # 30 - 10


@pytest.mark.unit
def test_split_missing_quarter_breaks_continuity() -> None:
    # 缺 20230630：20230930 的上期是 20230331，不是相邻上一季 → None（is_last=False）。
    out = _split([("20230331", 10.0), ("20230930", 60.0), ("20231231", 100.0)], "NP")
    assert out["20230930"] is None
    # 20231231 的上期是 20230930，相邻 → 有值
    assert out["20231231"] == pytest.approx(40.0)


@pytest.mark.unit
def test_split_da_interpolation_chain() -> None:
    # 折旧链：年报100、Q1缺失、半年报50、Q3缺失、年报110。
    # Q1插值=100/12×3=25；Q3插值=半年报50/6×9=75；单季 [None,25,25,25,35]。
    out = _split(
        [
            ("20221231", 100.0),
            ("20230331", None),
            ("20230630", 50.0),
            ("20230930", None),
            ("20231231", 110.0),
        ],
        "S_STM_IS",
    )
    assert out["20221231"] is None
    assert out["20230331"] == pytest.approx(25.0)
    assert out["20230630"] == pytest.approx(25.0)
    assert out["20230930"] == pytest.approx(25.0)
    assert out["20231231"] == pytest.approx(35.0)


@pytest.mark.unit
def test_rolling_ttm_full_window_and_nan_propagation() -> None:
    # 满4期才产值。
    vals = [Decimal(1), Decimal(2), Decimal(3), Decimal(4), Decimal(5)]
    out = rolling_ttm(vals)
    assert out[:3] == [None, None, None]
    assert out[3] == Decimal(10)
    assert out[4] == Decimal(14)
    # 含 None 传播：第4窗口含 None → None。
    vals2 = [Decimal(1), None, Decimal(3), Decimal(4), Decimal(5), Decimal(6)]
    out2 = rolling_ttm(vals2)
    assert out2[3] is None  # 窗口 [1,None,3,4]
    assert out2[4] is None  # 窗口 [None,3,4,5]
    assert out2[5] == Decimal(18)  # 窗口 [3,4,5,6]


@pytest.mark.unit
def test_latest_value() -> None:
    recs = tuple(_rec(p, "TOT_ASSETS", v) for p, v in [("20231231", 9000.0), ("20230930", 8800.0)])
    dm = dedupe_keep_last(recs)
    assert latest_value(dm["X"], "TOT_ASSETS") == Decimal("9000.0")
    assert latest_value(dm["X"], "MISSING") is None
    assert latest_value({}, "TOT_ASSETS") is None
