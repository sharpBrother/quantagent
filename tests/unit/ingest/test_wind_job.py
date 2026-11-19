"""Wind 分页作业：历史与日更共用，干跑默认一页。"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from dagster import DagsterInstance, DagsterRunStatus
from orchestration.resources.wind import WindIngestResource, _ingest_child, _PageProgress
from typer.testing import CliRunner

from quantagent.adapters.postgres.errors import TransactionUnknownError
from quantagent.adapters.postgres.src_targets import AINDEXVALUATION
from quantagent.cli.app import app
from quantagent.ingest.errors import IngestStoppedError, SourceFetchError
from quantagent.ingest.jobs import wind_paged
from quantagent.ingest.jobs.wind_paged import ingest_wind_paged
from quantagent.ingest.sources.wind.cursor import decode_cursor, initial_cursor
from quantagent.ingest.writers.tables import ASHARECALENDAR, ASHAREEODPRICES
from quantagent.platform.config import Settings
from quantagent.platform.storage.paths import resolve_var_paths

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from multiprocessing.connection import Connection
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


def _isolated_stop_child(
    *,
    settings: Settings,
    paths: VarPaths,
    table: str,
    write_db: bool,
    page_size: int,
    max_pages: int | None,
    progress_path: Path,
    conn: Connection,
    stop_path: Path,
) -> None:
    # 子进程使用真实分页和停止代码，仅将外部源与数据库换为隔离假对象。
    class BlockingSource(FakeWindSource):
        def fetch_page(self, **kwargs: object) -> list[dict[str, object]]:
            (paths.root / "fetching").touch()
            deadline = time.monotonic() + 30
            while not stop_path.exists():
                if time.monotonic() > deadline:
                    raise TimeoutError("未收到测试停止请求")
                time.sleep(0.02)
            return super().fetch_page(**kwargs)  # type: ignore[arg-type]

    class CommittedStore(FakeSrcStore):
        def commit(self) -> None:
            assert self.cursor is not None
            (paths.root / "committed_cursor").write_text(self.cursor, encoding="utf-8")

    source = BlockingSource([[_row("a", datetime(2024, 1, 2, 10))], []])
    store = CommittedStore()
    original = wind_paged.ingest_wind_paged

    def fake_connections(**kwargs: object) -> object:
        return original(source=source, store=store, **kwargs)  # type: ignore[arg-type]

    wind_paged.ingest_wind_paged = fake_connections  # type: ignore[assignment]
    _ingest_child(
        settings=settings,
        paths=paths,
        table=table,
        write_db=write_db,
        page_size=page_size,
        max_pages=max_pages,
        progress_path=progress_path,
        conn=conn,
        stop_path=stop_path,
    )


@pytest.mark.unit
def test_safe_stop_command_through_spawned_ingest_and_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "b0e4bc1a-df9f-4df4-a78b-26d378837f03"
    settings, paths = _paths(tmp_path)
    resource = WindIngestResource(settings=settings, paths=paths, stall_seconds=40)
    monkeypatch.setattr("quantagent.cli.ingest.get_settings", lambda: settings)
    monkeypatch.setattr("quantagent.cli.ingest.detect_repo_root", lambda: tmp_path)
    run = SimpleNamespace(job_name="wind_initial_backfill", status=DagsterRunStatus.STARTED)
    monkeypatch.setattr(
        DagsterInstance, "get", lambda: SimpleNamespace(get_run_by_id=lambda _: run)
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            resource._run_watched,
            "ASHAREEODPRICES",
            write_db=True,
            page_size=1000,
            max_pages=None,
            stop_run_id=run_id,
            child_target=_isolated_stop_child,
            poll_seconds=0.1,
        )
        deadline = time.monotonic() + 30
        while not (paths.root / "fetching").exists():
            if future.done():
                future.result()
                pytest.fail("采集子进程未进入源查询")
            if time.monotonic() > deadline:
                pytest.fail("等待采集子进程超时")
            time.sleep(0.02)
        result = CliRunner().invoke(app, ["ingest", "wind", "stop-after-page", "--run-id", run_id])
        assert result.exit_code == 0, result.output
        with pytest.raises(IngestStoppedError, match="已提交 1 页"):
            future.result(timeout=30)
    cursor = (paths.root / "committed_cursor").read_text(encoding="utf-8")
    assert decode_cursor(cursor).object_id == "a"
    log = _failure_log(paths)
    assert log["row_count"] == 1
    assert "按请求停止" in str(log["error"])
    resumed_source = FakeWindSource([[_row("b", datetime(2024, 1, 2, 11))], []])
    resumed = ingest_wind_paged(
        settings=settings,
        paths=paths,
        table="ASHAREEODPRICES",
        write_db=True,
        source=resumed_source,
        store=FakeSrcStore(cursor=cursor),
    )
    assert resumed_source.seen[0] == decode_cursor(cursor)
    assert decode_cursor(resumed.source_cursor).object_id == "b"


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


class _FixedClock:
    @staticmethod
    def monotonic() -> float:
        return 100.0


@pytest.mark.unit
@pytest.mark.parametrize("request_phase", ["source_fetch", "commit"])
def test_stop_after_commit_and_resume_from_committed_cursor(
    tmp_path: Path, request_phase: str
) -> None:
    settings, paths = _paths(tmp_path)
    marker = tmp_path / "stop"
    first = _row("a", datetime(2024, 1, 2, 10))
    second = _row("b", datetime(2024, 1, 2, 11))

    class RequestDuringFetch(FakeWindSource):
        def fetch_page(self, **kwargs: object) -> list[dict[str, object]]:
            rows = super().fetch_page(**kwargs)  # type: ignore[arg-type]
            if request_phase == "source_fetch":
                marker.touch()
            return rows

    source = RequestDuringFetch([[first], [second], []])

    class RequestDuringCommit(FakeSrcStore):
        def commit(self) -> None:
            super().commit()
            if request_phase == "commit":
                marker.touch()

    store = RequestDuringCommit()
    progress = _PageProgress(tmp_path / "progress", marker)
    with pytest.raises(IngestStoppedError, match="已提交 1 页"):
        ingest_wind_paged(
            settings=settings,
            paths=paths,
            table="ASHAREEODPRICES",
            write_db=True,
            source=source,
            store=store,
            on_page=progress,
        )
    assert len(source.seen) == 1
    assert decode_cursor(store.cursor).object_id == "a"
    assert (tmp_path / "progress").read_text() == "1"
    log = _failure_log(paths)
    assert log["status"] == "failure"
    assert log["row_count"] == 1
    assert "按请求停止" in str(log["error"])
    assert decode_cursor(str(log["error"]).split("source_cursor=", 1)[1]).object_id == "a"
    marker.unlink()
    result = ingest_wind_paged(
        settings=settings,
        paths=paths,
        table="ASHAREEODPRICES",
        write_db=True,
        source=source,
        store=store,
    )
    assert result.pages == 1
    assert source.seen[1].object_id == "a"
    assert decode_cursor(store.cursor).object_id == "b"


@pytest.mark.unit
def test_stop_request_does_not_mask_unknown_commit(tmp_path: Path) -> None:
    settings, paths = _paths(tmp_path)
    marker = tmp_path / "stop"
    marker.touch()

    class UnknownCommit(FakeSrcStore):
        def commit(self) -> None:
            raise TransactionUnknownError("commit uncertain")

    progress = _PageProgress(tmp_path / "progress", marker)
    with pytest.raises(TransactionUnknownError, match="commit uncertain"):
        ingest_wind_paged(
            settings=settings,
            paths=paths,
            table="ASHAREEODPRICES",
            write_db=True,
            source=FakeWindSource([[_row("a", datetime(2024, 1, 2, 10))]]),
            store=UnknownCommit(),
            on_page=progress,
        )
    assert not (tmp_path / "progress").exists()


@pytest.mark.unit
def test_slow_stage_logs_only_when_threshold_exceeded(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # configure_logging 会把 quantagent 的 propagate 设为 False；别的测试先跑过它时，caplog 收不到。
    monkeypatch.setattr(logging.getLogger("quantagent"), "propagate", True)
    monkeypatch.setattr(wind_paged, "time", _FixedClock())
    wind_paged._log_slow_stage("ASHAREEODPRICES", 1, "source_fetch", 71.0)
    assert not caplog.records
    wind_paged._log_slow_stage("ASHAREEODPRICES", 2, "pg_write_and_verify", 69.0)
    assert "page=2 pg_write_and_verify=31.0s" in caplog.text


@pytest.mark.unit
def test_page_phase_and_commit_order(tmp_path: Path) -> None:
    settings, paths = _paths(tmp_path)
    events: list[tuple[str, int]] = []

    class Progress:
        def mark_phase(
            self, phase: str, page: int, start_cursor: str, end_cursor: str | None = None
        ) -> None:
            assert start_cursor
            assert (end_cursor is not None) == (phase == "pg_write_and_verify")
            events.append((phase, page))

        def __call__(self, pages: int) -> None:
            events.append(("committed", pages))

    ingest_wind_paged(
        settings=settings,
        paths=paths,
        table="ASHAREEODPRICES",
        write_db=True,
        source=FakeWindSource([[_row("a", datetime(2024, 1, 2, 10))], []]),
        store=FakeSrcStore(),
        on_page=Progress(),
    )
    assert events == [
        ("source_fetch", 1),
        ("pg_write_and_verify", 1),
        ("committed", 1),
        ("source_fetch", 2),
    ]


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
