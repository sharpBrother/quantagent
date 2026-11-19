"""``quantagent ingest progress`` 与 ``ingest wind progress``：用桩替换数据库，只验证参数与输出。"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from quantagent.adapters.postgres.src_progress import SRC_SCHEMAS, TableProgress
from quantagent.cli.app import app
from quantagent.platform.config import Settings

if TYPE_CHECKING:
    from pathlib import Path


def _row(schema: str, dataset: str) -> TableProgress:
    return TableProgress(
        schema=schema,
        dataset=dataset,
        pages=3,
        rows=30,
        source_cursor=None,
        last_commit=datetime(2026, 11, 19, 9, 0, tzinfo=UTC),
        recent_pages=0,
        recent_seconds_per_page=None,
    )


@pytest.fixture
def recorder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    settings = Settings(_env_file=None, var_root=tmp_path / "var")
    monkeypatch.setattr("quantagent.cli.ingest.get_settings", lambda: settings)
    seen: dict[str, Any] = {}

    @contextmanager
    def fake_connect(_settings: object, plane: str) -> Any:
        seen["plane"] = plane
        yield MagicMock(name="conn")

    def fake_src_progress(
        _conn: object, *, schemas: tuple[str, ...], window_minutes: int
    ) -> list[TableProgress]:
        seen["schemas"] = tuple(schemas)
        seen["window"] = window_minutes
        return [_row(schemas[0], "src.demo.table")]

    monkeypatch.setattr("quantagent.cli.ingest.connect", fake_connect)
    monkeypatch.setattr("quantagent.cli.ingest.src_progress", fake_src_progress)
    return seen


@pytest.mark.unit
def test_progress_defaults_to_every_source_schema(recorder: dict[str, Any]) -> None:
    result = CliRunner().invoke(app, ["ingest", "progress"])
    assert result.exit_code == 0, result.output
    assert recorder["schemas"] == SRC_SCHEMAS
    assert recorder["plane"] == "src"
    assert recorder["window"] == 60
    header = result.output.splitlines()[0]
    assert header.startswith("schema")


@pytest.mark.unit
def test_progress_schema_option_limits_query(recorder: dict[str, Any]) -> None:
    result = CliRunner().invoke(
        app, ["ingest", "progress", "--schema", "src_tushare", "--schema", "src_macro"]
    )
    assert result.exit_code == 0, result.output
    assert recorder["schemas"] == ("src_tushare", "src_macro")
    assert "src_tushare" in result.output


@pytest.mark.unit
def test_progress_rejects_unknown_schema_before_connecting(recorder: dict[str, Any]) -> None:
    result = CliRunner().invoke(app, ["ingest", "progress", "--schema", "src_evil"])
    assert result.exit_code != 0
    assert "src_evil" in result.output
    assert "schemas" not in recorder


@pytest.mark.unit
def test_wind_progress_still_queries_only_src_wind_without_schema_column(
    recorder: dict[str, Any],
) -> None:
    result = CliRunner().invoke(app, ["ingest", "wind", "progress"])
    assert result.exit_code == 0, result.output
    assert recorder["schemas"] == ("src_wind",)
    assert result.output.splitlines()[0].startswith("dataset")
