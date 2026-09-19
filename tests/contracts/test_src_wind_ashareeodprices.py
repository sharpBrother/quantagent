"""Wind A 股日行情契约：schema 与 PIT 成对，游标字段不是可见日。"""

from __future__ import annotations

import pytest

from quantagent.contracts.check import run_check
from quantagent.contracts.loader import load_bundle
from quantagent.platform.storage import detect_repo_root


@pytest.mark.contracts
def test_ashareeodprices_bundle_pairs_schema_and_visibility() -> None:
    bundle = load_bundle()
    assert "src.wind.ashareeodprices" in bundle.schemas
    assert "src.wind.ashareeodprices" in bundle.visibilities
    schema = bundle.schemas["src.wind.ashareeodprices"]
    vis = bundle.visibilities["src.wind.ashareeodprices"]
    assert schema.keys == ["OBJECT_ID"]
    assert schema.event_field == "TRADE_DT"
    assert schema.columns["TRADE_DT"].dtype == "string"
    assert schema.columns["GSUPDTIME"].dtype == "bytes"
    assert vis.visibility.rule == "same_day_close"
    assert vis.visibility.grade == "A"
    assert vis.event_field == "TRADE_DT"
    assert vis.pit_recoverable is True
    report = run_check(bundle=bundle, repo_root=detect_repo_root())
    assert report.ok, [issue.render() for issue in report.issues]
