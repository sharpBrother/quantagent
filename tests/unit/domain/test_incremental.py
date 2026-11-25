"""日更增量的就绪判定与连续截止：阈值、前 5 日最大值、分钟登记、遇不就绪即停。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from quantagent.domain.errors import IncrementError
from quantagent.domain.incremental import (
    MINUTE_INPUT,
    ReadinessData,
    candidates_after,
    forward_span,
    is_input_ready,
    is_row_count_ready,
    plan_window,
)


def _opens(count: int, start: date = date(2024, 1, 1)) -> tuple[date, ...]:
    """连续的 ``count`` 个开市日（不跳周末，只测规则本身）。"""
    return tuple(start + timedelta(days=offset) for offset in range(count))


@pytest.mark.unit
def test_threshold_is_ninety_nine_percent_of_peak_inclusive() -> None:
    prior = [1000, 1000, 1000, 1000, 1000]
    assert is_row_count_ready(990, prior) is True
    assert is_row_count_ready(989, prior) is False


@pytest.mark.unit
def test_threshold_uses_max_of_exactly_the_five_prior_days() -> None:
    # 峰值只看前 5 个开市日的最大值；更早的高值不参与。
    assert is_row_count_ready(100, [100, 50, 50, 50, 50]) is True
    assert is_row_count_ready(98, [100, 50, 50, 50, 50]) is False


@pytest.mark.unit
def test_all_zero_prior_days_is_not_ready() -> None:
    # 前序全为空时没有基准，不能把"0 行"判成完整。
    assert is_row_count_ready(0, [0, 0, 0, 0, 0]) is False


@pytest.mark.unit
def test_prior_window_must_have_exactly_five_days() -> None:
    with pytest.raises(IncrementError, match="5 个前序开市日"):
        is_row_count_ready(10, [10, 10, 10, 10])


@pytest.mark.unit
def test_daily_input_compares_against_prior_five_open_days_only() -> None:
    opens = _opens(8)
    counts = {"ashareeodprices": dict.fromkeys(opens, 100)}
    counts["ashareeodprices"][opens[6]] = 0  # 第 7 个开市日缺行
    data = ReadinessData(opens=opens, counts=counts, minute_days=frozenset())
    assert is_input_ready(data, opens[5], ["ashareeodprices"]) is True
    assert is_input_ready(data, opens[6], ["ashareeodprices"]) is False
    # 第 8 天的前 5 日是 opens[2..6]，其中 opens[6] 为 0，峰值仍是 100，8 天的 100 行达标。
    assert is_input_ready(data, opens[7], ["ashareeodprices"]) is True


@pytest.mark.unit
def test_partial_day_is_blocked_by_any_missing_input() -> None:
    opens = _opens(8)
    full = dict.fromkeys(opens, 100)
    partial = dict(full)
    partial[opens[7]] = 50
    data = ReadinessData(
        opens=opens,
        counts={"ashareeodprices": full, "asharemoneyflow": partial},
        minute_days=frozenset(),
    )
    assert is_input_ready(data, opens[7], ["ashareeodprices"]) is True
    assert is_input_ready(data, opens[7], ["ashareeodprices", "asharemoneyflow"]) is False


@pytest.mark.unit
def test_minute_input_only_checks_registration() -> None:
    opens = _opens(8)
    data = ReadinessData(opens=opens, counts={}, minute_days=frozenset({opens[7]}))
    assert is_input_ready(data, opens[7], [MINUTE_INPUT]) is True
    assert is_input_ready(data, opens[6], [MINUTE_INPUT]) is False


@pytest.mark.unit
def test_unknown_source_is_rejected_not_skipped() -> None:
    opens = _opens(8)
    data = ReadinessData(opens=opens, counts={}, minute_days=frozenset())
    with pytest.raises(IncrementError, match="缺少输入"):
        is_input_ready(data, opens[7], ["ashareeodprices"])


@pytest.mark.unit
def test_day_outside_calendar_or_without_five_prior_days_raises() -> None:
    opens = _opens(8)
    data = ReadinessData(opens=opens, counts={"ashareeodprices": {}}, minute_days=frozenset())
    with pytest.raises(IncrementError, match="不在开市日历"):
        is_input_ready(data, date(2030, 1, 1), ["ashareeodprices"])
    with pytest.raises(IncrementError, match="不足 5 个"):
        is_input_ready(data, opens[3], ["ashareeodprices"])


@pytest.mark.unit
def test_window_stops_at_first_unready_day_and_ignores_later_ready_days() -> None:
    days = _opens(6)
    ready = {days[0], days[1], days[3], days[4]}  # days[2] 未就绪，之后即使就绪也不算
    window = plan_window(days, lambda day: day in ready)
    assert window.days == (days[0], days[1])
    assert window.start == days[0]
    assert window.cutoff == days[1]
    assert window.blocked_on == days[2]


@pytest.mark.unit
def test_window_with_everything_ready_has_no_blocked_day() -> None:
    days = _opens(3)
    window = plan_window(days, lambda _day: True)
    assert window.days == days
    assert window.blocked_on is None


@pytest.mark.unit
def test_window_first_day_unready_is_empty() -> None:
    days = _opens(3)
    window = plan_window(days, lambda _day: False)
    assert window.days == ()
    assert window.start is None
    assert window.cutoff is None
    assert window.blocked_on == days[0]


@pytest.mark.unit
def test_empty_candidates_means_no_new_data() -> None:
    window = plan_window((), lambda _day: True)
    assert window.candidates == ()
    assert window.days == ()
    assert window.blocked_on is None


@pytest.mark.unit
def test_candidates_are_strictly_after_watermark_and_not_after_as_of() -> None:
    opens = _opens(10)
    got = candidates_after(opens, after=opens[3], as_of=opens[7])
    assert got == opens[4:8]


@pytest.mark.unit
def test_forward_span_is_next_open_and_h_plus_one_th_open() -> None:
    opens = _opens(10)
    # 1d：起点是 T 后第 1 个开市日，终点是第 2 个。
    assert forward_span(opens, opens[2], 1) == (opens[3], opens[4])
    # 20d：终点是第 21 个开市日。
    assert forward_span(opens, opens[0], 20) is None
    assert forward_span(_opens(30), _opens(30)[0], 20) == (_opens(30)[1], _opens(30)[21])


@pytest.mark.unit
def test_forward_span_unavailable_when_end_is_not_in_calendar() -> None:
    opens = _opens(10)
    # 终点超出日历（尚未到期）时返回 None，由调用方视为未就绪。
    assert forward_span(opens, opens[8], 1) is None
    assert forward_span(opens, opens[7], 1) == (opens[8], opens[9])
