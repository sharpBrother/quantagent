"""``quantagent ingest macro fred``：命令注册、默认干跑与输出字段。假作业，不联网。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from quantagent.cli.app import app
from quantagent.ingest.jobs.macro_fred import MacroFredIngestResult, MacroFredSeriesResult
from quantagent.ingest.writers.src_follow import SrcFollowWriteResult

if TYPE_CHECKING:
    from pytest import MonkeyPatch

runner = CliRunner()


def _dry_result() -> MacroFredIngestResult:
    write = SrcFollowWriteResult(
        dataset="src.macro.fred_observation_vintage",
        written=False,
        row_count=3364,
        inserted=0,
        replaced=0,
        skipped=0,
        metadata_skipped=0,
        payload_digest="p" * 64,
        output_digest="p" * 64,
        dml_count=0,
        batch_id=None,
    )
    return MacroFredIngestResult(
        dataset="src.macro.fred_observation_vintage",
        written=False,
        series=(MacroFredSeriesResult(series_id="CPIAUCSL", pages=1, write=write),),
    )


@pytest.mark.unit
def test_fred_command_is_registered_under_macro_group() -> None:
    result = runner.invoke(app, ["ingest", "macro", "fred", "--help"])
    assert result.exit_code == 0
    assert "--series" in result.output
    assert "--write-db" in result.output


@pytest.mark.unit
def test_dry_run_prints_pages_and_rows_per_series(monkeypatch: MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    def _fake(**kwargs: object) -> MacroFredIngestResult:
        calls.update(kwargs)
        return _dry_result()

    monkeypatch.setattr("quantagent.cli.ingest.ingest_macro_fred", _fake)
    result = runner.invoke(app, ["ingest", "macro", "fred", "--series", "CPIAUCSL"])
    assert result.exit_code == 0, result.output
    assert calls["write_db"] is False
    assert calls["series_ids"] == ["CPIAUCSL"]
    expected = (
        "dry-run dataset=src.macro.fred_observation_vintage series=CPIAUCSL pages=1 rows=3364"
    )
    assert expected in result.output
