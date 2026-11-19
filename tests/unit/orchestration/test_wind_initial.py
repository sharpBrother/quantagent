"""初始化回填顺序与日常资产分离；使用假采集，不连接数据库。"""

import pytest
from orchestration.assets.wind import WIND_SOURCE_ASSETS
from orchestration.jobs.wind_initial import (
    INITIAL_BACKFILL_ORDER,
    initial_run_config,
    wind_initial_backfill,
)

from quantagent.ingest.jobs.wind_paged import WindPagedIngestResult
from quantagent.ingest.sources.wind.tables import WIND_PAGED_TABLES


class _Recorder:
    def __init__(self, fail: str | None = None) -> None:
        self.calls: list[tuple[str, bool, int, int | None]] = []
        self.fail = fail

    def ingest(
        self, table: str, *, write_db: bool, page_size: int, max_pages: int | None
    ) -> WindPagedIngestResult:
        self.calls.append((table, write_db, page_size, max_pages))
        if table == self.fail:
            raise RuntimeError("failed")
        return WindPagedIngestResult(
            dataset=f"src.wind.{table.lower()}",
            table=table,
            written=False,
            pages=0,
            row_count=0,
            inserted=0,
            replaced=0,
            deleted=0,
            skipped=0,
            metadata_skipped=0,
            dml_count=0,
            payload_digest="",
            output_digest="digest",
            source_cursor="cursor",
        )


@pytest.mark.unit
def test_initial_job_serializes_all_tables_without_changing_daily_lineage() -> None:
    assert set(INITIAL_BACKFILL_ORDER) == set(WIND_PAGED_TABLES)
    assert all(not asset.dependency_keys for asset in WIND_SOURCE_ASSETS)
    recorder = _Recorder()
    result = wind_initial_backfill.execute_in_process(
        resources={"wind_ingest": recorder}, run_config=initial_run_config("2026-11-19")
    )
    assert result.success
    assert recorder.calls == [(table, True, 1000, None) for table in INITIAL_BACKFILL_ORDER]
    materialized = []
    for event in result.get_asset_materialization_events():
        assert event.asset_key is not None
        materialized.append(event.asset_key.path[-1])
    assert materialized == [f"src_wind_{table.lower()}" for table in INITIAL_BACKFILL_ORDER]


@pytest.mark.unit
def test_initial_job_stops_after_first_failed_table() -> None:
    recorder = _Recorder(fail="ASHAREEODDERIVATIVEINDICATOR")
    result = wind_initial_backfill.execute_in_process(
        resources={"wind_ingest": recorder},
        run_config=initial_run_config("2026-11-19"),
        raise_on_error=False,
    )
    assert not result.success
    assert [call[0] for call in recorder.calls] == list(INITIAL_BACKFILL_ORDER[:2])
