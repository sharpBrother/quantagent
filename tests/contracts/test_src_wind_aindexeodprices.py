"""Wind 指数日行情契约：schema 与 PIT 成对，游标字段不是可见日。"""

from __future__ import annotations

import pytest

from quantagent.adapters.postgres.src_targets import AINDEXEODPRICES
from quantagent.contracts.check import run_check
from quantagent.contracts.loader import load_bundle
from quantagent.platform.storage import detect_repo_root

_SOURCE_COLUMNS = (
    "OBJECT_ID",
    "S_INFO_WINDCODE",
    "TRADE_DT",
    "CRNCY_CODE",
    "S_DQ_PRECLOSE",
    "S_DQ_OPEN",
    "S_DQ_HIGH",
    "S_DQ_LOW",
    "S_DQ_CLOSE",
    "S_DQ_CHANGE",
    "S_DQ_PCTCHANGE",
    "S_DQ_VOLUME",
    "S_DQ_AMOUNT",
    "SEC_ID",
    "OPDATE",
    "OPMODE",
    "gsCTime",
    "gsUTime",
    "mopdate",
)


@pytest.mark.contracts
def test_aindexeodprices_bundle_pairs_schema_and_visibility() -> None:
    bundle = load_bundle()
    assert "src.wind.aindexeodprices" in bundle.schemas
    assert "src.wind.aindexeodprices" in bundle.visibilities
    schema = bundle.schemas["src.wind.aindexeodprices"]
    vis = bundle.visibilities["src.wind.aindexeodprices"]
    assert AINDEXEODPRICES.native_columns == _SOURCE_COLUMNS
    assert "S_INFO_NAME" not in AINDEXEODPRICES.native_columns
    assert "INDEX_INTRO" not in AINDEXEODPRICES.native_columns
    assert schema.keys == ["OBJECT_ID"]
    assert schema.event_field == "TRADE_DT"
    assert vis.visibility.rule == "same_day_close"
    assert vis.visibility.grade == "A"
    assert vis.pit_recoverable is True
    report = run_check(bundle=bundle, repo_root=detect_repo_root())
    assert report.ok, [issue.render() for issue in report.issues]
