"""金十 ISM 详情的事件身份和发布时间校验。"""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from quantagent.ingest.errors import IngestError, SourceFetchError
from quantagent.ingest.jobs.jin10_ism_details import ingest_jin10_ism_details
from quantagent.ingest.sources.macro.jin10_ism import parse_jin10_ism_detail
from quantagent.platform.config import Settings
from quantagent.platform.storage import resolve_var_paths


def _payload() -> dict[str, object]:
    return {
        "status": 200,
        "data": {
            "dataId": 1178751,
            "datanameId": 129,
            "pub_time": "2026-11-02T15:00:00.000Z",
            "public_time": "2026-11-02 23:00:00",
            "time_period": "10月",
            "actual": "55.5",
            "consensus": "54.6",
            "previous": "54.5",
        },
    }


@pytest.mark.unit
def test_detail_preserves_time_and_release_values() -> None:
    result = parse_jin10_ism_detail(_payload(), requested_id=1178751)
    assert result.published_at == datetime(2026, 11, 2, 15, tzinfo=UTC)
    assert result.publish_date == date(2026, 11, 2)
    assert result.period_end == date(2026, 10, 31)
    assert (result.actual_value, result.forecast_value, result.previous_value) == (
        Decimal("55.5"),
        Decimal("54.6"),
        Decimal("54.5"),
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("dataId", 1),
        ("datanameId", 99),
        ("pub_time", "2026-11-02T15:00:00"),
        ("public_time", "2026-11-02 22:00:00"),
        ("time_period", "未知"),
        ("actual", "NaN"),
    ],
)
def test_reject_mismatched_or_invalid_source(field: str, bad: object) -> None:
    payload = _payload()
    data = payload["data"]
    assert isinstance(data, dict)
    data[field] = bad
    with pytest.raises(SourceFetchError):
        parse_jin10_ism_detail(payload, requested_id=1178751)


@pytest.mark.unit
def test_january_release_uses_prior_year_and_preserves_missing() -> None:
    payload = _payload()
    data = payload["data"]
    assert isinstance(data, dict)
    data.update(
        pub_time="2026-01-05T15:00:00Z",
        public_time="2026-01-05 23:00:00",
        time_period="12月",
        consensus=None,
    )
    result = parse_jin10_ism_detail(payload, requested_id=1178751)
    assert result.period_end == date(2025, 12, 31)
    assert result.forecast_value is None


@pytest.mark.unit
def test_details_job_dry_run_and_source_identity(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, var_root=tmp_path)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    item = parse_jin10_ism_detail(_payload(), requested_id=1178751)
    result = ingest_jin10_ism_details(
        settings=settings, paths=paths, event_ids=[1178751], fetch=lambda _: item
    )
    assert not result.written
    assert result.row_count == 1
    assert result.dml_count == 0
    assert len(list(paths.runs.glob("*.json"))) == 1


@pytest.mark.unit
def test_details_job_rejects_repeated_ids(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, var_root=tmp_path)
    with pytest.raises(IngestError, match="重复"):
        ingest_jin10_ism_details(
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            event_ids=[1, 1],
        )
