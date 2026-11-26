"""nap_adj_ratio 库函数单元测试：窗口裁剪、entrytime 可见性、并列年度、中位数。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from quantagent.domain.fundamental.types import EarningsAdjustRecord
from quantagent.features.library.fundamental.nap_adj_ratio import (
    adjust_window_rows,
    nap_adj_ratio,
)


def _row(
    create: str,
    entry: str,
    year: int | None,
    rate: str | None,
    code: str = "000001.SZ",
) -> EarningsAdjustRecord:
    return EarningsAdjustRecord(
        asset_id=code,
        create_dt=date.fromisoformat(create),
        entry_dt=date.fromisoformat(entry),
        report_year=year,
        np_adjust_rate=Decimal(rate) if rate is not None else None,
    )


@pytest.mark.unit
def test_empty_rows_no_value() -> None:
    assert nap_adj_ratio(as_of=date(2024, 5, 15), rows=[]) is None


@pytest.mark.unit
def test_single_year_median() -> None:
    rows = [
        _row("2024-05-10", "2024-05-10", 2024, "0.10"),
        _row("2024-05-12", "2024-05-12", 2024, "0.20"),
        _row("2024-05-14", "2024-05-14", 2024, "0.30"),
    ]
    # 全部 2024 年，中位数 0.20
    assert nap_adj_ratio(as_of=date(2024, 5, 15), rows=rows) == Decimal("0.20")


@pytest.mark.unit
def test_even_count_median_is_mean_of_middle_two() -> None:
    rows = [
        _row("2024-05-10", "2024-05-10", 2024, "0.10"),
        _row("2024-05-11", "2024-05-11", 2024, "0.20"),
        _row("2024-05-12", "2024-05-12", 2024, "0.30"),
        _row("2024-05-13", "2024-05-13", 2024, "0.40"),
    ]
    # 偶数个取中间两值 0.20/0.30 的均值 0.25（pandas quantile(0.5) 线性插值）
    assert nap_adj_ratio(as_of=date(2024, 5, 15), rows=rows) == Decimal("0.25")


@pytest.mark.unit
def test_most_adjusted_year_wins() -> None:
    # 2023 年 3 条，2024 年 1 条，取 2023 年（条数最多）
    rows = [
        _row("2024-05-10", "2024-05-10", 2023, "0.10"),
        _row("2024-05-11", "2024-05-11", 2023, "0.20"),
        _row("2024-05-12", "2024-05-12", 2023, "0.30"),
        _row("2024-05-13", "2024-05-13", 2024, "0.99"),
    ]
    assert nap_adj_ratio(as_of=date(2024, 5, 15), rows=rows) == Decimal("0.20")


@pytest.mark.unit
def test_tied_years_pick_smaller_year() -> None:
    # 2023 与 2024 并列各 2 条，复现旧仓 sort_values index[0]：取较小年度 2023
    rows = [
        _row("2024-05-10", "2024-05-10", 2023, "0.10"),
        _row("2024-05-11", "2024-05-11", 2023, "0.30"),
        _row("2024-05-12", "2024-05-12", 2024, "0.50"),
        _row("2024-05-13", "2024-05-13", 2024, "0.70"),
    ]
    # 取 2023 年，中位数 (0.10+0.30)/2 = 0.20
    assert nap_adj_ratio(as_of=date(2024, 5, 15), rows=rows) == Decimal("0.20")


@pytest.mark.unit
def test_window_excludes_rows_older_than_30_days() -> None:
    rows = [
        _row("2024-04-14", "2024-04-14", 2024, "0.99"),  # create 早于 04-15（30天前），排除
        _row("2024-05-10", "2024-05-10", 2024, "0.20"),
    ]
    # 窗口 [04-15, 05-15]，只有 0.20 一条
    assert nap_adj_ratio(as_of=date(2024, 5, 15), rows=rows) == Decimal("0.20")


@pytest.mark.unit
def test_window_boundary_inclusive() -> None:
    # create 恰好 30 天前（04-15）与当天（05-15）都含在窗口内
    rows = [
        _row("2024-04-15", "2024-04-15", 2024, "0.10"),
        _row("2024-05-15", "2024-05-15", 2024, "0.30"),
    ]
    assert nap_adj_ratio(as_of=date(2024, 5, 15), rows=rows) == Decimal("0.20")


@pytest.mark.unit
def test_entry_after_as_of_excluded() -> None:
    """entrytime 晚于观察日的行不可见，剔除。这是消除前视的关键。"""
    rows = [
        # create 在窗口内，但 entry 晚于 as_of（05-16 > 05-15），不可见
        _row("2024-05-10", "2024-05-16", 2024, "0.99"),
        _row("2024-05-12", "2024-05-12", 2024, "0.20"),
    ]
    assert nap_adj_ratio(as_of=date(2024, 5, 15), rows=rows) == Decimal("0.20")


@pytest.mark.unit
def test_all_entries_after_as_of_no_value() -> None:
    rows = [_row("2024-05-10", "2024-05-20", 2024, "0.99")]
    assert nap_adj_ratio(as_of=date(2024, 5, 15), rows=rows) is None


@pytest.mark.unit
def test_null_report_year_excluded_from_grouping() -> None:
    rows = [
        _row("2024-05-10", "2024-05-10", None, "0.99"),  # report_year 空，groupby 排除
        _row("2024-05-12", "2024-05-12", 2024, "0.20"),
    ]
    assert nap_adj_ratio(as_of=date(2024, 5, 15), rows=rows) == Decimal("0.20")


@pytest.mark.unit
def test_null_np_adjust_rate_excluded_from_median() -> None:
    rows = [
        _row("2024-05-10", "2024-05-10", 2024, None),  # rate 空，pandas 跳过
        _row("2024-05-12", "2024-05-12", 2024, "0.20"),
    ]
    assert nap_adj_ratio(as_of=date(2024, 5, 15), rows=rows) == Decimal("0.20")


@pytest.mark.unit
def test_all_rates_null_no_value() -> None:
    rows = [
        _row("2024-05-10", "2024-05-10", 2024, None),
        _row("2024-05-12", "2024-05-12", 2024, None),
    ]
    assert nap_adj_ratio(as_of=date(2024, 5, 15), rows=rows) is None


@pytest.mark.unit
def test_adjust_window_rows_visible_and_window() -> None:
    rows = [
        _row("2024-05-10", "2024-05-10", 2024, "0.1"),  # 在窗口且可见
        _row("2024-05-10", "2024-05-20", 2024, "0.2"),  # entry 晚于 as_of
        _row("2024-04-01", "2024-04-01", 2024, "0.3"),  # create 早于窗口
    ]
    win = adjust_window_rows(as_of=date(2024, 5, 15), rows=rows)
    assert len(win) == 1
    assert win[0].np_adjust_rate == Decimal("0.1")
