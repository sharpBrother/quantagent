"""Wind 指数日行情契约：schema 与 PIT 成对，游标字段不是可见日。"""

from __future__ import annotations

import pytest

from quantagent.contracts.check import run_check
from quantagent.contracts.loader import load_bundle
from quantagent.platform.storage import detect_repo_root


@pytest.mark.contracts
def test_aindexeodprices_bundle_pairs_schema_and_visibility() -> None:
    bundle = load_bundle()
    assert "src.wind.aindexeodprices" in bundle.schemas
    assert "src.wind.aindexeodprices" in bundle.visibilities
    schema = bundle.schemas["src.wind.aindexeodprices"]
    vis = bundle.visibilities["src.wind.aindexeodprices"]
    assert schema.keys == ["OBJECT_ID"]
    assert schema.event_field == "TRADE_DT"
    assert vis.visibility.rule == "same_day_close"
    assert vis.visibility.grade == "A"
    assert vis.pit_recoverable is True
    report = run_check(bundle=bundle, repo_root=detect_repo_root())
    assert report.ok, [issue.render() for issue in report.issues]
