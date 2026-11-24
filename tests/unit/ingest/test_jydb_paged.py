"""聚源 JYDB 分页采集：SQL、游标、干跑、每页提交与续跑。"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from quantagent.adapters.postgres.src_targets import JYDB_SPECS
from quantagent.ingest.errors import SourceFetchError
from quantagent.ingest.jobs.jydb_paged import ingest_jydb_paged
from quantagent.ingest.sources.jydb.cursor import (
    JydbCursor,
    cursor_from_row,
    decode_cursor,
    initial_cursor,
)
from quantagent.ingest.sources.jydb.paged import build_page_params, build_page_sql
from quantagent.ingest.writers.src_follow import business_columns, fingerprint_columns
from quantagent.ingest.writers.src_insert import row_hash
from quantagent.platform.config.settings import Settings
from quantagent.platform.storage import resolve_var_paths

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

_SPEC = JYDB_SPECS["C_ED_MacroIndicatorData"]
_NOW = datetime(2024, 1, 5, 12, 0, tzinfo=UTC)


class _FakeSource:
    def __init__(self, rows: Sequence[Mapping[str, object]], *, null_jsid: int = 0) -> None:
        self.rows = sorted(rows, key=lambda row: (row["JSID"], row["ID"]))
        self.null_jsid = null_jsid
        self.cursors: list[JydbCursor] = []

    def source_columns(self, table: str) -> list[str]:
        return list(_SPEC.native_columns)

    def null_jsid_count(self, table: str) -> int:
        return self.null_jsid

    def fetch_page(
        self,
        *,
        table: str,
        columns: Sequence[str],
        cursor: JydbCursor,
        limit: int,
    ) -> list[dict[str, object]]:
        self.cursors.append(cursor)
        picked = [
            dict(row) for row in self.rows if (row["JSID"], row["ID"]) > (cursor.jsid, cursor.id)
        ]
        return picked[:limit]


class _FakeStore:
    def __init__(self) -> None:
        self.state: dict[tuple[object, ...], dict[str, Any]] = {}
        self.committed = deepcopy(self.state)
        self.batches: list[dict[str, Any]] = []
        self.inserted: list[Mapping[str, object]] = []
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
        self.batches.append(
            {"id": batch_id, "source_cursor": source_cursor, "row_count": row_count}
        )
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
            key = (row["ID"],)
            self.state[key] = {
                "hash": digest,
                "batch": batch_id,
                "values": {name: row[name] for name in business_columns(_SPEC)},
            }
        self.inserted.extend(rows)

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
            key = (row["ID"],)
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


def _row(jsid: int, object_id: int, value: str = "1.5") -> dict[str, object]:
    return {
        "ID": object_id,
        "IndicatorCode": 110255493,
        "InfoPublDate": datetime(2024, 1, 10, 9, 30),
        "EndDate": datetime(2023, 12, 31),
        "DataValue": Decimal(value),
        "PowerNumber": 0,
        "UpdateTime": datetime(2024, 1, 10, 9, 0),
        "JSID": jsid,
    }


def _settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, allow_db_write=True, var_root=tmp_path / "var")


@pytest.mark.unit
def test_page_sql_uses_jsid_id_cursor_and_parameters() -> None:
    sql = build_page_sql(table="C_ED_MacroIndicatorData", columns=("ID", "JSID"), limit=10)
    assert sql == (
        "SELECT TOP (10) [ID], [JSID] FROM [dbo].[C_ED_MacroIndicatorData] "
        "WHERE [JSID] IS NOT NULL AND [ID] IS NOT NULL "
        "AND ([JSID] > %s OR ([JSID] = %s AND [ID] > %s)) "
        "ORDER BY [JSID], [ID]"
    )
    cursor = JydbCursor(jsid=9, id=40)
    assert build_page_params(cursor) == (9, 9, 40)
    assert sql.count("%s") == 3


@pytest.mark.unit
def test_cursor_round_trip_and_rejects_bad_shape() -> None:
    cursor = JydbCursor(jsid=12, id=34)
    assert decode_cursor(cursor.encode()) == cursor
    assert decode_cursor(None) == initial_cursor()
    with pytest.raises(SourceFetchError, match="形状不符"):
        decode_cursor('{"jsid": 1}')
    with pytest.raises(SourceFetchError, match="不是整数"):
        decode_cursor('{"jsid": true, "id": 2}')
    # pymssql 的 bigint 常以 Decimal 返回；整数值必须还原成游标整数。
    assert cursor_from_row({"JSID": Decimal("848761529805"), "ID": Decimal("12")}) == JydbCursor(
        848761529805, 12
    )


@pytest.mark.unit
def test_dry_run_reads_one_page_without_store(tmp_path: Path) -> None:
    source = _FakeSource([_row(1, 10), _row(2, 11), _row(3, 12)])
    result = ingest_jydb_paged(
        settings=_settings(tmp_path),
        paths=resolve_var_paths(_settings(tmp_path), repo_root=tmp_path),
        table="C_ED_MacroIndicatorData",
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
    result = ingest_jydb_paged(
        settings=settings,
        paths=paths,
        table="C_ED_MacroIndicatorData",
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
    assert decode_cursor(store.last_cursor) == JydbCursor(jsid=3, id=12)

    resumed_source = _FakeSource([_row(1, 10), _row(2, 11), _row(3, 12)])
    resumed = ingest_jydb_paged(
        settings=settings,
        paths=paths,
        table="C_ED_MacroIndicatorData",
        write_db=True,
        source=resumed_source,
        store=store,
        page_size=2,
        now=lambda: _NOW,
    )
    assert resumed.pages == 0
    assert resumed_source.cursors == [JydbCursor(jsid=3, id=12)]


@pytest.mark.unit
def test_null_jsid_and_column_drift_fail_closed(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    with pytest.raises(SourceFetchError, match="JSID 为空"):
        ingest_jydb_paged(
            settings=settings,
            paths=paths,
            table="C_ED_MacroIndicatorData",
            source=_FakeSource([_row(1, 10)], null_jsid=2),
            now=lambda: _NOW,
        )

    class _Drift(_FakeSource):
        def source_columns(self, table: str) -> list[str]:
            return [*super().source_columns(table), "EXTRA"]

    with pytest.raises(SourceFetchError, match="源端列与代码不一致"):
        ingest_jydb_paged(
            settings=settings,
            paths=paths,
            table="C_ED_MacroIndicatorData",
            source=_Drift([_row(1, 10)]),
            now=lambda: _NOW,
        )


@pytest.mark.unit
def test_fingerprint_excludes_jydb_system_columns() -> None:
    assert set(fingerprint_columns(_SPEC)) == {
        "ID",
        "IndicatorCode",
        "InfoPublDate",
        "EndDate",
        "DataValue",
        "PowerNumber",
    }
    assert row_hash(_row(1, 10), fingerprint_columns(_SPEC)) == row_hash(
        {**_row(1, 10), "UpdateTime": datetime(2030, 1, 1), "JSID": 999},
        fingerprint_columns(_SPEC),
    )
