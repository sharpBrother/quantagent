"""朝阳永续分页采集：SQL、游标、干跑、每页提交与续跑。"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from quantagent.adapters.postgres.src_targets import SUNTIME_SPECS
from quantagent.ingest.errors import SourceFetchError
from quantagent.ingest.jobs.suntime_paged import ingest_suntime_paged
from quantagent.ingest.sources.suntime.cursor import (
    SuntimeCursor,
    cursor_from_row,
    decode_cursor,
    initial_cursor,
)
from quantagent.ingest.sources.suntime.paged import build_page_params, build_page_sql
from quantagent.ingest.writers.src_follow import business_columns, fingerprint_columns
from quantagent.ingest.writers.src_insert import row_hash
from quantagent.platform.config.settings import Settings
from quantagent.platform.storage import resolve_var_paths

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

_SPEC = SUNTIME_SPECS["con_forecast_roll_idx"]
_NOW = datetime(2024, 1, 5, 12, 0, tzinfo=UTC)


class _FakeSource:
    def __init__(self, rows: Sequence[Mapping[str, object]], *, null_cursor: int = 0) -> None:
        self.rows = sorted(rows, key=lambda row: (row["tmstamp"], row["id"]))
        self.null_cursor = null_cursor
        self.cursors: list[SuntimeCursor] = []

    def source_columns(self, table: str) -> list[str]:
        return list(_SPEC.native_columns)

    def null_cursor_count(self, table: str) -> int:
        return self.null_cursor

    def fetch_page(
        self,
        *,
        table: str,
        columns: Sequence[str],
        cursor: SuntimeCursor,
        limit: int,
    ) -> list[dict[str, object]]:
        self.cursors.append(cursor)
        picked = [
            dict(row)
            for row in self.rows
            if (row["tmstamp"], row["id"]) > (cursor.tmstamp, cursor.id)
        ]
        return picked[:limit]


class _FakeStore:
    def __init__(self) -> None:
        self.state: dict[tuple[object, ...], dict[str, Any]] = {}
        self.committed = deepcopy(self.state)
        self.batches: list[dict[str, Any]] = []
        self.last_cursor: str | None = None
        self.next_batch = 1

    def latest_source_cursor(self, spec: object) -> str | None:
        return self.last_cursor

    def existing_keys(
        self, spec: object, keys: Sequence[tuple[object, ...]]
    ) -> set[tuple[object, ...]]:
        return {key for key in keys if key in self.state}

    def existing_hashes(
        self, spec: object, keys: Sequence[tuple[object, ...]]
    ) -> dict[tuple[object, ...], str]:
        return {key: self.state[key]["hash"] for key in keys if key in self.state}

    def existing_values(
        self,
        spec: object,
        keys: Sequence[tuple[object, ...]],
        columns: Sequence[str],
    ) -> dict[tuple[object, ...], tuple[object, ...]]:
        return {
            key: tuple(self.state[key]["values"][name] for name in columns)
            for key in keys
            if key in self.state
        }

    def insert_batch(
        self,
        *,
        spec: object,
        window_start: str | None,
        window_end: str | None,
        row_count: int,
        payload_digest: str,
        started_at: datetime,
        finished_at: datetime,
        source_cursor: str | None = None,
    ) -> int:
        batch_id = self.next_batch
        self.next_batch += 1
        self.batches.append({"id": batch_id, "source_cursor": source_cursor})
        self.last_cursor = source_cursor
        return batch_id

    def delete_keys(self, spec: object, keys: Sequence[tuple[object, ...]]) -> None:
        for key in keys:
            self.state.pop(key, None)

    def insert_rows(
        self,
        spec: object,
        rows: Sequence[Mapping[str, object]],
        *,
        hashes: Sequence[str],
        batch_id: int,
        ingested_at: datetime,
    ) -> None:
        for row, digest in zip(rows, hashes, strict=True):
            key = (row["id"],)
            self.state[key] = {
                "hash": digest,
                "batch": batch_id,
                "values": {name: row[name] for name in business_columns(_SPEC)},
            }

    def readback_hashes(
        self, spec: object, batch_id: int, keys: Sequence[tuple[object, ...]]
    ) -> list[str]:
        return [
            self.state[key]["hash"]
            for key in keys
            if key in self.state and self.state[key]["batch"] == batch_id
        ]

    def mismatched_rows(
        self, spec: object, batch_id: int, rows: Sequence[Mapping[str, object]]
    ) -> list[tuple[object, ...]]:
        bad: list[tuple[object, ...]] = []
        for row in rows:
            key = (row["id"],)
            stored = self.state.get(key)
            if stored is None or any(
                stored["values"][name] != row[name] for name in business_columns(_SPEC)
            ):
                bad.append(key)
        return bad

    def commit(self) -> None:
        self.committed = deepcopy(self.state)

    def rollback(self) -> None:
        self.state = deepcopy(self.committed)


def _row(tmstamp: int, row_id: int, value: float = 1.5) -> dict[str, object]:
    return {
        "id": row_id,
        "index_code": "000300",
        "index_name": "沪深300",
        "con_date": date(2024, 1, 10),
        "con_or_roll": value,
        "con_np_roll": value,
        "con_eps_roll": value,
        "con_na_roll": value,
        "con_pb_roll": value,
        "con_ps_roll": value,
        "con_pe_roll": value,
        "con_peg_roll": value,
        "con_roe_roll": value,
        "con_npcgrate_2y_roll": value,
        "con_or_yoy_roll": value,
        "con_np_yoy_roll": value,
        "entrytime": datetime(2024, 1, 10, 18, 0),
        "updatetime": datetime(2024, 1, 10, 18, 0),
        "tmstamp": tmstamp,
    }


def _settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, allow_db_write=True, var_root=tmp_path / "var")


@pytest.mark.unit
def test_page_sql_uses_tmstamp_id_cursor_and_parameters() -> None:
    sql = build_page_sql(table="con_forecast_roll_idx", columns=("id", "tmstamp"), limit=10)
    assert sql == (
        "SELECT TOP (10) [id], [tmstamp] FROM [dbo].[con_forecast_roll_idx] "
        "WHERE [tmstamp] IS NOT NULL AND [id] IS NOT NULL "
        "AND ([tmstamp] > %s OR ([tmstamp] = %s AND [id] > %s)) "
        "ORDER BY [tmstamp], [id]"
    )
    cursor = SuntimeCursor(tmstamp=9, id=40)
    assert build_page_params(cursor) == (9, 9, 40)
    assert sql.count("%s") == 3


@pytest.mark.unit
def test_cursor_round_trip_and_rejects_bad_shape() -> None:
    cursor = SuntimeCursor(tmstamp=12, id=34)
    assert decode_cursor(cursor.encode()) == cursor
    assert decode_cursor(None) == initial_cursor()
    with pytest.raises(SourceFetchError, match="形状不符"):
        decode_cursor('{"tmstamp": 1}')
    with pytest.raises(SourceFetchError, match="不是整数"):
        decode_cursor('{"tmstamp": true, "id": 2}')
    assert cursor_from_row({"tmstamp": Decimal("848761529805"), "id": Decimal("12")}) == (
        SuntimeCursor(848761529805, 12)
    )


@pytest.mark.unit
def test_dry_run_reads_one_page_without_store(tmp_path: Path) -> None:
    source = _FakeSource([_row(1, 10), _row(2, 11), _row(3, 12)])
    result = ingest_suntime_paged(
        settings=_settings(tmp_path),
        paths=resolve_var_paths(_settings(tmp_path), repo_root=tmp_path),
        table="con_forecast_roll_idx",
        source=source,
        page_size=2,
        now=lambda: _NOW,
    )
    assert result.written is False
    assert result.pages == 1
    assert result.row_count == 2
    assert source.cursors == [initial_cursor()]
    assert result.batch_ids == ()


@pytest.mark.unit
def test_write_commits_each_page_and_resumes_from_last_cursor(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    source = _FakeSource([_row(1, 10), _row(2, 11), _row(3, 12)])
    store = _FakeStore()
    result = ingest_suntime_paged(
        settings=settings,
        paths=paths,
        table="con_forecast_roll_idx",
        write_db=True,
        source=source,
        store=store,
        page_size=2,
        now=lambda: _NOW,
    )
    assert result.pages == 2
    assert result.row_count == 3
    assert result.inserted == 3
    assert len(store.batches) == 2
    assert store.last_cursor is not None
    assert decode_cursor(store.last_cursor) == SuntimeCursor(tmstamp=3, id=12)

    resumed_source = _FakeSource([_row(1, 10), _row(2, 11), _row(3, 12)])
    resumed = ingest_suntime_paged(
        settings=settings,
        paths=paths,
        table="con_forecast_roll_idx",
        write_db=True,
        source=resumed_source,
        store=store,
        page_size=2,
        now=lambda: _NOW,
    )
    assert resumed.pages == 0
    assert resumed_source.cursors == [SuntimeCursor(tmstamp=3, id=12)]


@pytest.mark.unit
def test_null_cursor_and_column_drift_fail_closed(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    with pytest.raises(SourceFetchError, match="为空"):
        ingest_suntime_paged(
            settings=settings,
            paths=paths,
            table="con_forecast_roll_idx",
            source=_FakeSource([_row(1, 10)], null_cursor=2),
            now=lambda: _NOW,
        )

    class _Drift(_FakeSource):
        def source_columns(self, table: str) -> list[str]:
            return [*super().source_columns(table), "EXTRA"]

    with pytest.raises(SourceFetchError, match="源端列与代码不一致"):
        ingest_suntime_paged(
            settings=settings,
            paths=paths,
            table="con_forecast_roll_idx",
            source=_Drift([_row(1, 10)]),
            now=lambda: _NOW,
        )


@pytest.mark.unit
def test_fingerprint_excludes_suntime_system_columns() -> None:
    assert "entrytime" not in fingerprint_columns(_SPEC)
    assert "updatetime" not in fingerprint_columns(_SPEC)
    assert "tmstamp" not in fingerprint_columns(_SPEC)
    assert "id" in fingerprint_columns(_SPEC)
    assert "con_np_roll" in fingerprint_columns(_SPEC)
    assert row_hash(_row(1, 10), fingerprint_columns(_SPEC)) == row_hash(
        {**_row(1, 10), "updatetime": datetime(2030, 1, 1), "tmstamp": 999},
        fingerprint_columns(_SPEC),
    )
