"""CLI 入口：check contracts 与 db status / migrate。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from quantagent.cli.app import app
from quantagent.platform.config import cache_clear
from quantagent.platform.config.settings import Settings

if TYPE_CHECKING:
    from collections.abc import Generator

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _plain(result: object) -> str:
    """去掉 Rich ANSI。CI=true 时颜色码会插进 ``--as-of`` 中间。"""
    output = getattr(result, "output", "")
    if not isinstance(output, str):
        return ""
    return _ANSI.sub("", output)


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    cache_clear()
    monkeypatch.setenv("COLUMNS", "120")
    settings = Settings(_env_file=None)
    monkeypatch.setattr("quantagent.cli.db.get_settings", lambda: settings)
    monkeypatch.setattr("quantagent.cli.lake.get_settings", lambda: settings)
    monkeypatch.setattr("quantagent.cli.ingest.get_settings", lambda: settings)
    monkeypatch.setattr("quantagent.cli.calendar.get_settings", lambda: settings)
    monkeypatch.setattr("quantagent.cli.feature.get_settings", lambda: settings)
    monkeypatch.setattr("quantagent.cli.forward_return.get_settings", lambda: settings)
    monkeypatch.setattr("quantagent.cli.group_nav.get_settings", lambda: settings)
    yield
    cache_clear()


@pytest.mark.contracts
def test_check_contracts_passes_on_real_bundle() -> None:
    result = runner.invoke(app, ["check", "contracts"])
    assert result.exit_code == 0, result.output
    assert "ok" in _plain(result)


@pytest.mark.unit
def test_db_status_does_not_require_postgres() -> None:
    result = runner.invoke(app, ["db", "status"])
    text = _plain(result)
    assert result.exit_code == 0, result.output
    assert "profile" in text
    assert "var_root" in text
    assert "allow_db_write" in text
    assert "pg src" in text
    assert "pg ops" in text
    assert "未配置" in text
    assert "migrate" in text


@pytest.mark.unit
def test_db_migrate_without_write_db_does_not_write() -> None:
    result = runner.invoke(app, ["db", "migrate"])
    text = _plain(result)
    assert result.exit_code == 1, result.output
    assert "未配置" in text or "拒绝写库" in text


@pytest.mark.unit
def test_db_migrate_help_lists_write_db() -> None:
    result = runner.invoke(app, ["db", "migrate", "--help"])
    text = _plain(result)
    assert result.exit_code == 0
    assert "--write-db" in text
    assert "--plane" in text


@pytest.mark.unit
def test_root_help_lists_check_db_ingest_and_lake() -> None:
    result = runner.invoke(app, ["--help"])
    text = _plain(result)
    assert result.exit_code == 0
    assert "check" in text
    assert "db" in text
    assert "calendar" in text
    assert "feature" in text
    assert "forward-return" in text
    assert "group-nav" in text
    assert "ingest" in text
    assert "lake" in text


@pytest.mark.unit
def test_calendar_is_open_help_requires_as_of() -> None:
    result = runner.invoke(app, ["calendar", "is-open", "--help"])
    text = _plain(result)
    assert result.exit_code == 0
    assert "--as-of" in text
    assert "--cal-dt" in text
    assert "--exchange" in text


@pytest.mark.unit
def test_feature_window_help_requires_as_of() -> None:
    result = runner.invoke(app, ["feature", "window", "--help"])
    text = _plain(result)
    assert result.exit_code == 0
    assert "--as-of" in text
    assert "--feature-id" in text
    assert "--start" in text
    assert "--end" in text


@pytest.mark.unit
def test_forward_return_window_help_requires_as_of() -> None:
    result = runner.invoke(app, ["forward-return", "window", "--help"])
    text = _plain(result)
    assert result.exit_code == 0
    assert "--as-of" in text
    assert "--horizon" in text
    assert "--return-kind" in text


@pytest.mark.unit
def test_feature_metric_help_requires_as_of() -> None:
    result = runner.invoke(app, ["feature", "metric", "--help"])
    text = _plain(result)
    assert result.exit_code == 0
    assert "--as-of" in text
    assert "--metric-id" in text
    assert "--universe-id" in text


@pytest.mark.unit
def test_group_nav_window_help_requires_as_of() -> None:
    result = runner.invoke(app, ["group-nav", "window", "--help"])
    text = _plain(result)
    assert result.exit_code == 0
    assert "--as-of" in text
    assert "--run-id" in text
    assert "--universe-id" in text


@pytest.mark.unit
def test_feature_window_missing_lake_fails_closed() -> None:
    result = runner.invoke(
        app,
        [
            "feature",
            "window",
            "--feature-id",
            "mom_20d",
            "--definition-version",
            "v1",
            "--param-hash",
            "p0",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-31",
            "--as-of",
            "2024-01-10",
        ],
    )
    text = _plain(result)
    assert result.exit_code == 1
    assert "Traceback" not in text
    assert "parquet 源不存在" in text or "因子窗口为空" in text


@pytest.mark.unit
def test_ingest_trade_cal_help_lists_write_db() -> None:
    result = runner.invoke(app, ["ingest", "tushare", "trade-cal", "--help"])
    text = _plain(result)
    assert result.exit_code == 0
    assert "--write-db" in text
    assert "--start" in text
    assert "--exchange" in text


@pytest.mark.unit
def test_lake_materialize_trade_calendar_help() -> None:
    result = runner.invoke(app, ["lake", "materialize", "trade-calendar", "--help"])
    text = _plain(result)
    assert result.exit_code == 0
    assert "--as-of" in text
    assert "--rebuild" in text


@pytest.mark.unit
def test_lake_benchmark_layout_help() -> None:
    result = runner.invoke(app, ["lake", "benchmark-layout", "--help"])
    text = _plain(result)
    assert result.exit_code == 0
    assert "--scale" in text
    assert "--rebuild" in text
