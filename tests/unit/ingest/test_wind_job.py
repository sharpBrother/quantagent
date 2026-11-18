"""Wind 分页作业：历史与日更共用，干跑默认一页。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from quantagent.adapters.postgres.errors import TransactionUnknownError
from quantagent.adapters.postgres.src_targets import AINDEXVALUATION
from quantagent.ingest.errors import SourceFetchError
from quantagent.ingest.jobs.wind_paged import ingest_wind_paged
from quantagent.ingest.sources.wind.cursor import decode_cursor, initial_cursor
from quantagent.ingest.writers.tables import ASHARECALENDAR, ASHAREEODPRICES
from quantagent.platform.config import Settings
from quantagent.platform.storage.paths import resolve_var_paths

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from quantagent.adapters.postgres.src_targets import SrcTableWriteSpec
    from quantagent.ingest.sources.wind.cursor import WindCursor
    from quantagent.platform.storage.paths import VarPaths


class FakeWindSource:
    def __init__(
        self,
        pages: Sequence[Sequence[dict[str, object]]],
        *,
        spec: SrcTableWriteSpec = ASHAREEODPRICES,
    ) -> None:
        self.pages = [list(page) for page in pages]
        self.spec = spec
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
        assert table == self.spec.pg_table
        assert tuple(columns) == self.spec.native_columns
        if not self.pages:
            return []
        return self.pages.pop(0)


class FakeSrcStore:
    def __init__(self, cursor: str | None = None) -> None:
        self.cursor = cursor
        self.hashes: dict[tuple[object, ...], str] = {}
        self.values: dict[tuple[object, ...], Mapping[str, object]] = {}
        self.batch_cursors: list[str | None] = []
        self.batch_windows: list[tuple[str | None, str | None]] = []
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

    def existing_values(
        self,
        spec: object,
        keys: Sequence[tuple[object, ...]],
        columns: Sequence[str],
    ) -> dict[tuple[object, ...], tuple[object, ...]]:
        return {
            key: tuple(self.values[key][name] for name in columns)
            for key in keys
            if key in self.values
        }

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
        self.batch_windows.append((window_start, window_end))
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

    def readback_hashes(
        self, spec: object, batch_id: int, keys: Sequence[tuple[object, ...]]
    ) -> list[str]:
        return list(getattr(self, "_last", []))

    def mismatched_rows(
        self, spec: object, batch_id: int, rows: Sequence[Mapping[str, object]]
    ) -> list[tuple[object, ...]]:
        return list(getattr(self, "forced_mismatch", []))

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def _paths(tmp_path: Path) -> tuple[Settings, VarPaths]:
    settings = Settings(
        _env_file=None, profile="office", var_root=tmp_path / "var", allow_db_write=True
    )
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


@pytest.mark.unit
def test_calendar_initialization_and_incremental_resume(tmp_path: Path) -> None:
    settings, paths = _paths(tmp_path)
    opdate = datetime(2024, 1, 2, 10)
    first = dict.fromkeys(ASHARECALENDAR.native_columns)
    first.update(
        OBJECT_ID="a",
        TRADE_DAYS="20240103",
        S_INFO_EXCHMARKET="SSE",
        OPDATE=opdate,
        OPMODE="0",
    )
    second = {**first, "OBJECT_ID": "b", "TRADE_DAYS": "20240102"}
    store = FakeSrcStore()
    initial_source = FakeWindSource([[first]], spec=ASHARECALENDAR)
    initial = ingest_wind_paged(
        settings=settings,
        paths=paths,
        table=ASHARECALENDAR.pg_table,
        write_db=True,
        max_pages=1,
        source=initial_source,
        store=store,
    )
    assert initial_source.seen == [initial_cursor()]
    assert initial.inserted == 1
    incremental_source = FakeWindSource([[second]], spec=ASHARECALENDAR)
    incremental = ingest_wind_paged(
        settings=settings,
        paths=paths,
        table=ASHARECALENDAR.pg_table,
        write_db=True,
        source=incremental_source,
        store=store,
    )
    assert incremental_source.seen[0] == decode_cursor(initial.source_cursor)
    assert incremental.dataset == ASHARECALENDAR.dataset
    assert incremental.inserted == 1
    assert decode_cursor(incremental.source_cursor).object_id == "b"
    assert store.batch_windows == [("20240103", "20240103"), ("20240102", "20240102")]


class _SecondFetchFails(FakeWindSource):
    def fetch_page(
        self,
        *,
        table: str,
        columns: Sequence[str],
        cursor: WindCursor,
        limit: int,
        chi_fields: tuple[str, ...] = (),
    ) -> list[dict[str, object]]:
        if self.seen:
            self.seen.append(cursor)
            raise SourceFetchError("第二页读取失败")
        return super().fetch_page(
            table=table,
            columns=columns,
            cursor=cursor,
            limit=limit,
            chi_fields=chi_fields,
        )


class _UnknownOnSecondCommit(FakeSrcStore):
    def __init__(self) -> None:
        super().__init__()
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1
        if self.commits == 2:
            raise TransactionUnknownError("提交结果未知")


def _failure_log(paths: VarPaths) -> dict[str, object]:
    logs = sorted(paths.runs.glob("*.json"))
    assert len(logs) == 1
    payload = json.loads(logs[0].read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


@pytest.mark.unit
def test_failure_log_keeps_committed_page(tmp_path: Path) -> None:
    settings, paths = _paths(tmp_path)
    first = _row("a", datetime(2024, 1, 2, 10, 0, 0))
    second = _row("b", datetime(2024, 1, 2, 11, 0, 0))
    source = _SecondFetchFails([[first], [second]])
    with pytest.raises(SourceFetchError, match="第二页读取失败"):
        ingest_wind_paged(
            settings=settings,
            paths=paths,
            table="ASHAREEODPRICES",
            write_db=True,
            source=source,
            store=FakeSrcStore(),
        )
    assert len(source.seen) == 2
    log = _failure_log(paths)
    assert log["status"] == "failure"
    assert log["dml_count"] == 2
    assert log["row_count"] == 1
    error = str(log["error"])
    assert "已提交页 pages=1" in error
    assert decode_cursor(error.split("source_cursor=", 1)[1]).object_id == "a"


@pytest.mark.unit
def test_unknown_commit_stops_without_counting_or_retrying(tmp_path: Path) -> None:
    settings, paths = _paths(tmp_path)
    first = _row("a", datetime(2024, 1, 2, 10, 0, 0))
    second = _row("b", datetime(2024, 1, 2, 11, 0, 0))
    source = FakeWindSource([[first], [second]])
    store = _UnknownOnSecondCommit()
    with pytest.raises(TransactionUnknownError, match="提交结果未知"):
        ingest_wind_paged(
            settings=settings,
            paths=paths,
            table="ASHAREEODPRICES",
            write_db=True,
            source=source,
            store=store,
        )
    assert len(source.seen) == 2
    assert store.commits == 2
    log = _failure_log(paths)
    assert log["dml_count"] == 2
    assert log["row_count"] == 1
    assert decode_cursor(str(log["error"]).split("source_cursor=", 1)[1]).object_id == "a"


class _ColumnSource(FakeWindSource):
    def __init__(
        self,
        columns: list[str],
        *,
        spec: SrcTableWriteSpec = ASHAREEODPRICES,
    ) -> None:
        super().__init__([], spec=spec)
        self.columns = columns

    def source_columns(self, table: str) -> list[str]:
        return list(self.columns)


@pytest.mark.unit
def test_source_column_mismatch_stops_before_fetch(tmp_path: Path) -> None:
    settings, paths = _paths(tmp_path)
    source = _ColumnSource(["OBJECT_ID"])
    with pytest.raises(SourceFetchError, match="列与源表不一致"):
        ingest_wind_paged(
            settings=settings,
            paths=paths,
            table="AINDEXVALUATION",
            write_db=False,
            source=source,
            store=FakeSrcStore(),
        )
    assert source.seen == []


@pytest.mark.unit
def test_source_column_case_difference_is_tolerated(tmp_path: Path) -> None:
    # wind_db 的 ASHAREMONEYFLOW 列名是 MOPDATE，spec 写 mopdate；
    # SQL Server 不分大小写，取数按 spec 里的写法回键名，两者是同一列。
    settings, paths = _paths(tmp_path)
    source = _ColumnSource(
        [name.upper() for name in AINDEXVALUATION.native_columns], spec=AINDEXVALUATION
    )
    result = ingest_wind_paged(
        settings=settings,
        paths=paths,
        table="AINDEXVALUATION",
        write_db=False,
        source=source,
        store=FakeSrcStore(),
    )
    assert result.pages == 0


@pytest.mark.unit
def test_on_page_called_after_each_committed_page(tmp_path: Path) -> None:
    settings, paths = _paths(tmp_path)
    source = FakeWindSource(
        [
            [_row("a", datetime(2024, 1, 2, 10, 0, 0))],
            [_row("b", datetime(2024, 1, 2, 11, 0, 0))],
            [],
        ]
    )
    seen: list[int] = []
    result = ingest_wind_paged(
        settings=settings,
        paths=paths,
        table="ASHAREEODPRICES",
        write_db=True,
        source=source,
        store=FakeSrcStore(),
        on_page=seen.append,
    )
    assert result.pages == 2
    assert seen == [1, 2]


@pytest.mark.unit
def test_on_page_called_in_dry_run(tmp_path: Path) -> None:
    settings, paths = _paths(tmp_path)
    seen: list[int] = []
    ingest_wind_paged(
        settings=settings,
        paths=paths,
        table="ASHAREEODPRICES",
        write_db=False,
        source=FakeWindSource([[_row("a", datetime(2024, 1, 2, 10, 0, 0))]]),
        store=FakeSrcStore(),
        on_page=seen.append,
    )
    assert seen == [1]


class _PageCallbackFails(RuntimeError):
    pass


def _raise_on_page(pages: int) -> None:
    raise _PageCallbackFails(f"回调在第 {pages} 页失败")


@pytest.mark.unit
def test_on_page_exception_aborts_job(tmp_path: Path) -> None:
    settings, paths = _paths(tmp_path)
    source = FakeWindSource(
        [[_row("a", datetime(2024, 1, 2, 10, 0, 0))], [_row("b", datetime(2024, 1, 2, 11, 0, 0))]]
    )
    with pytest.raises(_PageCallbackFails, match="第 1 页"):
        ingest_wind_paged(
            settings=settings,
            paths=paths,
            table="ASHAREEODPRICES",
            write_db=True,
            source=source,
            store=FakeSrcStore(),
            on_page=_raise_on_page,
        )
    assert len(source.seen) == 1
