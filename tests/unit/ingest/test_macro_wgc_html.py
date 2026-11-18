"""旧 WGC HTML 解析口径与历史日期映射。"""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from quantagent.ingest.errors import IngestError, SourceFetchError
from quantagent.ingest.jobs.macro_wgc_html import build_rows, select_new_rows
from quantagent.ingest.sources.macro.wgc_html import latest_report_url, parse_report

_FIXTURE = Path(__file__).parents[2] / "golden" / "macro" / "wgc_q2_2026.html"


@pytest.mark.unit
def test_old_report_fixture_matches_old_21_categories() -> None:
    day, sha, points = parse_report(_FIXTURE.read_text())
    assert day == "20260730"
    assert len(sha) == 64
    assert len(points) == 105
    assert ("20250630", "BARS", Decimal("250.70000000")) in points
    assert ("20260630", "BARS", Decimal("247.80000000")) in points
    assert len({category for _, category, _ in points}) == 21


@pytest.mark.unit
def test_legacy_report_date_mapping_and_hash() -> None:
    stamp = datetime(2026, 11, 18)
    points = [("20250630", "BARS", Decimal("250.70000000"))]
    rows = build_rows("20260730", "a" * 64, points, {"20250630": "20250731"}, stamp)
    assert rows[0]["publish_date"] == "20250731"
    assert (
        rows[0]["record_hash"] == "5a8c04944514fdbf71affb1da2af04794a057a53510b1133544b4a99f1d146e1"
    )


@pytest.mark.unit
def test_same_business_record_skips_dynamic_html_but_conflict_fails() -> None:
    rows = build_rows(
        "20260730",
        "a" * 64,
        [("20250630", "BARS", Decimal("250.70000000"))],
        {"20250630": "20250731"},
        datetime(2026, 11, 18),
    )
    row = rows[0]
    key = (row["record_hash"],)
    value = tuple(
        row[col]
        for col in ("period_end", "geography", "category", "value_tonnes", "publish_date", "source")
    )
    assert select_new_rows(rows, {}) == rows
    assert select_new_rows(rows, {key: value}) == []
    with pytest.raises(IngestError, match="冲突"):
        select_new_rows(rows, {key: (*value[:-1], "other")})


@pytest.mark.unit
def test_missing_report_date_or_category_fails() -> None:
    html = _FIXTURE.read_text()
    with pytest.raises(SourceFetchError):
        parse_report(html.replace("<time datetime=", "<span datetime="))
    with pytest.raises(SourceFetchError):
        parse_report(html.replace("Mine Production", "Missing Production"))


@pytest.mark.unit
def test_latest_link_rejects_external_domain() -> None:
    with pytest.raises(SourceFetchError):
        latest_report_url(
            '<a href="https://elsewhere.test/gold-demand-trends">Read the latest Gold Demand Trends</a>'
        )
