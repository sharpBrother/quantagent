"""same_day_close：event_dt <= as_of；其它规则 fail-closed。"""

from __future__ import annotations

from datetime import date

import pytest

from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.errors import PitUnsupportedError
from quantagent.domain.pit import is_point_event_visible, visible_event_on_or_before


def _contract(*, rule: str = "same_day_close") -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": "std.trade_calendar",
            "doc_ref": "docs/contracts/trade-calendar.md",
            "temporal_kind": "point_event",
            "event_field": "cal_dt",
            "visibility": {
                "rule": rule,
                "grade": "A" if rule == "same_day_close" else "C",
                "rationale": "单元测试用的可见性规则说明必须足够长",
                **({"field": "published_at"} if rule == "source_field" else {}),
            },
            "pit_recoverable": True,
        }
    )


@pytest.mark.unit
def test_same_day_close_includes_as_of() -> None:
    contract = _contract()
    as_of = date(2026, 9, 16)
    assert visible_event_on_or_before(contract, as_of=as_of) == as_of
    assert is_point_event_visible(contract, event_dt=date(2026, 9, 16), as_of=as_of)
    assert is_point_event_visible(contract, event_dt=date(2026, 9, 15), as_of=as_of)
    assert not is_point_event_visible(contract, event_dt=date(2026, 9, 17), as_of=as_of)


@pytest.mark.unit
def test_unimplemented_rule_is_fail_closed() -> None:
    contract = _contract(rule="source_field")
    with pytest.raises(PitUnsupportedError, match="尚未实现"):
        visible_event_on_or_before(contract, as_of=date(2026, 9, 16))
