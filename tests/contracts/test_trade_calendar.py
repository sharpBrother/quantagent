"""真实 lake 契约：交易日历必须能加载、能通过完整性检查、能校验样本。"""

from __future__ import annotations

import pandas as pd
import pytest
from pandera.errors import SchemaError

from quantagent.contracts.check import run_check
from quantagent.contracts.loader import load_bundle
from quantagent.contracts.pandera_schema import to_pandera
from quantagent.platform.storage import detect_repo_root


@pytest.mark.contracts
def test_trade_calendar_bundle_is_complete() -> None:
    bundle = load_bundle()
    assert "std.trade_calendar" in bundle.schemas
    assert "std.trade_calendar" in bundle.visibilities
    report = run_check(bundle=bundle, repo_root=detect_repo_root())
    assert report.ok, [issue.render() for issue in report.issues]


@pytest.mark.contracts
def test_trade_calendar_visibility_grade_and_rule() -> None:
    vis = load_bundle().visibilities["std.trade_calendar"]
    assert vis.visibility.rule == "same_day_close"
    assert vis.visibility.grade == "A"
    assert vis.pit_recoverable is True
    assert vis.pit_from is None
    assert "published_at" not in load_bundle().schemas["std.trade_calendar"].columns


@pytest.mark.contracts
def test_trade_calendar_pandera_accepts_sample() -> None:
    spec = load_bundle().schemas["std.trade_calendar"]
    frame = pd.DataFrame(
        {
            "cal_dt": ["2026-01-01", "2026-01-05"],
            "exchange": ["SSE", "SSE"],
            "is_open": [False, True],
            "prev_trade_dt": [None, "2025-12-31"],
        }
    )
    to_pandera(spec).validate(frame)


@pytest.mark.contracts
def test_trade_calendar_pandera_rejects_missing_column() -> None:
    spec = load_bundle().schemas["std.trade_calendar"]
    frame = pd.DataFrame({"cal_dt": ["2026-01-05"], "exchange": ["SSE"], "is_open": [True]})
    with pytest.raises(SchemaError, match="prev_trade_dt"):
        to_pandera(spec).validate(frame)
