"""Wind 分页作业：历史与日更共用，干跑默认一页。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from quantagent.ingest.jobs.wind_paged import ingest_wind_paged
from quantagent.ingest.sources.wind.cursor import decode_cursor, initial_cursor
from quantagent.ingest.writers.tables import ASHAREEODPRICES
from quantagent.platform.config import Settings
from quantagent.platform.storage.paths import resolve_var_paths

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from quantagent.ingest.sources.wind.cursor import WindCursor
    from quantagent.platform.storage.paths import VarPaths


class FakeWindSource:
    def __init__(self, pages: Sequence[Sequence[dict[str, object]]]) -> None:
        self.pages = [list(page) for page in pages]
        self.seen: list[WindCursor] = []

    def fetch_page(
        self,
        *,
        table: str,
        columns: Sequence[str],
        cursor: WindCursor,
        limit: int,
        chi_fields: tuple[str, ...] = (),
    ) -> list[dict[str, object]]:
        self.seen.append(cursor)
        assert table == "ASHAREEODPRICES"
        assert tuple(columns) == ASHAREEODPRICES.native_columns
        if not self.pages:
            return []
        return self.pages.pop(0)


class FakeSrcStore:
    def __init__(self, cursor: str | None = None) -> None:
        self.cursor = cursor
        self.hashes: dict[tuple[object, ...], str] = {}
        self.batch_cursors: list[str | None] = []
        self.inserted = 0

    def existing_keys(
        self, spec: object, keys: Sequence[tuple[object, ...]]
    ) -> set[tuple[object, ...]]:
        return set(self.hashes)

    def existing_hashes(
        self,
        spec: object,
        keys: Sequence[tuple[object, ...]],
    ) -> dict[tuple[object, ...], str]:
        return {key: self.hashes[key] for key in keys if key in self.hashes}

    def latest_source_cursor(self, spec: object) -> str | None:
        return self.cursor

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
        self.batch_cursors.append(source_cursor)
        self.cursor = source_cursor
        return len(self.batch_cursors)

    def delete_keys(self, spec: object, keys: Sequence[tuple[object, ...]]) -> None:
        return None

    def insert_rows(
        self,
        spec: object,
        rows: Sequence[object],
        *,
        hashes: Sequence[str],
        batch_id: int,
        ingested_at: datetime,
    ) -> None:
        self.inserted += len(rows)
        self._last = list(hashes)

    def readback_hashes(self, spec: object, batch_id: int) -> list[str]:
        return list(getattr(self, "_last", []))

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def _paths(tmp_path: Path) -> tuple[Settings, VarPaths]:
    settings = Settings(_env_file=None, var_root=tmp_path / "var", allow_db_write=True)
    return settings, resolve_var_paths(settings, repo_root=tmp_path)


def _row(object_id: str, opdate: datetime) -> dict[str, object]:
    payload = dict.fromkeys(ASHAREEODPRICES.native_columns)
    payload.update(
        {
            "OBJECT_ID": object_id,
            "S_INFO_WINDCODE": "000001.SZ",
            "TRADE_DT": "20240102",
            "OPDATE": opdate,
            "OPMODE": "0",
        }
    )
    return payload


@pytest.mark.unit
def test_dry_run_defaults_to_one_page(tmp_path: Path) -> None:
    settings, paths = _paths(tmp_path)
    page1 = [_row("a", datetime(2024, 1, 2, 10, 0, 0))]
    page2 = [_row("b", datetime(2024, 1, 2, 11, 0, 0))]
    source = FakeWindSource([page1, page2])
    result = ingest_wind_paged(
        settings=settings,
        paths=paths,
        table="ASHAREEODPRICES",
        write_db=False,
        source=source,
        store=FakeSrcStore(),
    )
    assert result.pages == 1
    assert result.written is False
    assert result.row_count == 1
    assert len(source.seen) == 1
    assert source.seen[0] == initial_cursor()


@pytest.mark.unit
def test_write_walks_pages_and_resumes_from_batch_cursor(tmp_path: Path) -> None:
    settings, paths = _paths(tmp_path)
    first = _row("a", datetime(2024, 1, 2, 10, 0, 0))
    second = _row("b", datetime(2024, 1, 2, 11, 0, 0))
    source = FakeWindSource([[first], [second], []])
    store = FakeSrcStore()
    result = ingest_wind_paged(
        settings=settings,
        paths=paths,
        table="ASHAREEODPRICES",
        write_db=True,
        source=source,
        store=store,
    )
    assert result.pages == 2
    assert result.written is True
    assert result.inserted == 2
    assert store.inserted == 2
    assert decode_cursor(store.cursor).object_id == "b"
    assert source.seen[0] == initial_cursor()
    assert source.seen[1].object_id == "a"
    assert source.seen[2].object_id == "b"


@pytest.mark.unit
def test_empty_stream_is_success(tmp_path: Path) -> None:
    settings, paths = _paths(tmp_path)
    result = ingest_wind_paged(
        settings=settings,
        paths=paths,
        table="ASHAREEODPRICES",
        write_db=True,
        source=FakeWindSource([]),
        store=FakeSrcStore(),
    )
    assert result.pages == 0
    assert result.row_count == 0
    assert result.written is False
    assert decode_cursor(result.source_cursor) == initial_cursor()
