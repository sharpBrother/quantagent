"""聚源采集看门狗：停滞终止并报错、正常返回、子进程报错、页循环的阶段标记。

替身子进程只用模块顶层函数；源库与目标库全部用假对象，不连接任何 SQL Server 或 PG。
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from orchestration.resources.jydb import JydbIngestResource, _jydb_child
from orchestration.resources.watchdog import PageProgress

from quantagent.adapters.postgres.src_targets import JYDB_SPECS
from quantagent.ingest.errors import IngestStalledError
from quantagent.ingest.jobs.jydb_paged import ingest_jydb_paged
from quantagent.platform.config.settings import Settings
from quantagent.platform.storage import resolve_var_paths

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from multiprocessing.connection import Connection
    from pathlib import Path

    from quantagent.ingest.sources.jydb.cursor import JydbCursor
    from quantagent.platform.storage.paths import VarPaths

_TABLE = "C_ED_MacroIndicatorData"
_SPEC = JYDB_SPECS[_TABLE]
_NOW = datetime(2024, 1, 5, 12, 0, tzinfo=UTC)


def _hang(*, progress_path: Path, conn: Connection, **_: object) -> None:
    PageProgress(progress_path).mark_phase("source_fetch", 3)
    time.sleep(3600)


def _ok(*, progress_path: Path, conn: Connection, **_: object) -> None:
    conn.send(("ok", {"pages": 0, "table": "QT_OSINDEXQUOTE"}))
    conn.close()


def _resource(tmp_path: Path, *, stall_seconds: float) -> tuple[JydbIngestResource, VarPaths]:
    settings = Settings(_env_file=None, var_root=tmp_path / "var", allow_db_write=False)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    return JydbIngestResource(settings=settings, paths=paths, stall_seconds=stall_seconds), paths


class _Recorder:
    """记录 on_page 与阶段标记，用来核对页循环的调用顺序。"""

    def __init__(self) -> None:
        self.phases: list[tuple[str, int]] = []
        self.pages: list[int] = []

    def __call__(self, pages: int) -> None:
        self.pages.append(pages)

    def mark_phase(
        self,
        phase: str,
        page: int,
        start_cursor: str | None = None,
        end_cursor: str | None = None,
    ) -> None:
        self.phases.append((phase, page))


class _FakeSource:
    def __init__(self, rows: Sequence[Mapping[str, object]]) -> None:
        self.rows = sorted(rows, key=lambda row: (row["JSID"], row["ID"]))

    def source_columns(self, table: str) -> list[str]:
        return list(_SPEC.native_columns)

    def null_jsid_count(self, table: str) -> int:
        return 0

    def fetch_page(
        self,
        *,
        table: str,
        columns: Sequence[str],
        cursor: JydbCursor,
        limit: int,
    ) -> list[dict[str, object]]:
        picked = [
            dict(row) for row in self.rows if (row["JSID"], row["ID"]) > (cursor.jsid, cursor.id)
        ]
        return picked[:limit]


def _row(jsid: int, object_id: int) -> dict[str, object]:
    return {
        "ID": object_id,
        "IndicatorCode": 110255493,
        "InfoPublDate": datetime(2024, 1, 10, 9, 30),
        "EndDate": datetime(2023, 12, 31),
        "DataValue": Decimal("1.5"),
        "PowerNumber": 0,
        "UpdateTime": datetime(2024, 1, 10, 9, 0),
        "JSID": jsid,
    }


@pytest.mark.unit
def test_stalled_jydb_child_is_terminated_and_error_names_table_and_stage(tmp_path: Path) -> None:
    resource, paths = _resource(tmp_path, stall_seconds=1)
    started = time.monotonic()
    with pytest.raises(IngestStalledError) as excinfo:
        resource._run_watched(
            "QT_OSINDEXQUOTE",
            write_db=True,
            page_size=1000,
            max_pages=None,
            child_target=_hang,
            poll_seconds=0.1,
            term_grace_seconds=0.5,
        )
    assert time.monotonic() - started < 20
    message = str(excinfo.value)
    assert "QT_OSINDEXQUOTE" in message
    assert "source_fetch" in message
    assert "须核实事务状态后再决定是否续跑" in message
    failure = next((paths.logs / "jydb_ingest_progress").glob("*.failure.json"))
    record = json.loads(failure.read_text(encoding="utf-8"))
    assert json.loads(record["stage"])["page"] == 3


@pytest.mark.unit
def test_jydb_ok_result_is_returned_unchanged(tmp_path: Path) -> None:
    resource, paths = _resource(tmp_path, stall_seconds=30)
    result: object = resource._run_watched(
        "QT_OSINDEXQUOTE",
        write_db=False,
        page_size=10,
        max_pages=1,
        child_target=_ok,
        poll_seconds=0.1,
    )
    assert result == {"pages": 0, "table": "QT_OSINDEXQUOTE"}
    assert list((paths.logs / "jydb_ingest_progress").iterdir()) == []


@pytest.mark.unit
def test_jydb_child_reports_exceptions_as_error_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[object] = []

    class _Conn:
        def send(self, value: object) -> None:
            sent.append(value)

        def close(self) -> None:
            pass

    def boom(**kwargs: object) -> None:
        raise ValueError("源库不可达")

    monkeypatch.setattr("quantagent.ingest.jobs.jydb_paged.ingest_jydb_paged", boom)
    settings = Settings(_env_file=None, var_root=tmp_path / "var", allow_db_write=False)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    _jydb_child(
        settings=settings,
        paths=paths,
        table="QT_OSINDEXQUOTE",
        write_db=False,
        page_size=10,
        max_pages=1,
        progress_path=tmp_path / "progress",
        conn=_Conn(),  # type: ignore[arg-type]
    )
    assert sent == [("error", "ValueError: 源库不可达")]


@pytest.mark.unit
def test_page_loop_marks_fetch_and_write_stages_without_touching_commit_clock(
    tmp_path: Path,
) -> None:
    settings = Settings(_env_file=None, var_root=tmp_path / "var", allow_db_write=False)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    recorder = _Recorder()
    result = ingest_jydb_paged(
        settings=settings,
        paths=paths,
        table=_TABLE,
        source=_FakeSource([_row(1, 10), _row(2, 11), _row(3, 12)]),
        page_size=2,
        max_pages=1,
        now=lambda: _NOW,
        on_page=recorder,
    )
    assert result.pages == 1
    assert recorder.phases == [("source_fetch", 1), ("dry_run", 1)]
    assert recorder.pages == [1]


@pytest.mark.unit
def test_jydb_child_passes_progress_callback_to_the_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    class _Conn:
        def send(self, value: object) -> None:
            captured["sent"] = value

        def close(self) -> None:
            pass

    def fake_job(**kwargs: object) -> str:
        captured["on_page"] = kwargs["on_page"]
        return "result"

    monkeypatch.setattr("quantagent.ingest.jobs.jydb_paged.ingest_jydb_paged", fake_job)
    settings = Settings(_env_file=None, var_root=tmp_path / "var", allow_db_write=False)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    _jydb_child(
        settings=settings,
        paths=paths,
        table="QT_OSINDEXQUOTE",
        write_db=False,
        page_size=10,
        max_pages=1,
        progress_path=tmp_path / "progress",
        conn=_Conn(),  # type: ignore[arg-type]
    )
    assert isinstance(captured["on_page"], PageProgress)
    assert captured["sent"] == ("ok", "result")
    stage = json.loads((tmp_path / "progress.stage.json").read_text(encoding="utf-8"))
    assert stage["phase"] == "initializing"
