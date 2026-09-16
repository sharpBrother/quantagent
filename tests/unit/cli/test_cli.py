"""CLI 入口：check contracts 与 db status / migrate。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from quantagent.cli.app import app
from quantagent.platform.config import cache_clear
from quantagent.platform.config.settings import Settings

if TYPE_CHECKING:
    from collections.abc import Generator

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    cache_clear()
    settings = Settings(_env_file=None)
    monkeypatch.setattr("quantagent.cli.db.get_settings", lambda: settings)
    yield
    cache_clear()


@pytest.mark.contracts
def test_check_contracts_passes_on_real_bundle() -> None:
    result = runner.invoke(app, ["check", "contracts"])
    assert result.exit_code == 0, result.output
    assert "ok" in result.stdout


@pytest.mark.unit
def test_db_status_does_not_require_postgres() -> None:
    result = runner.invoke(app, ["db", "status"])
    assert result.exit_code == 0, result.output
    assert "profile" in result.stdout
    assert "var_root" in result.stdout
    assert "allow_db_write" in result.stdout
    assert "pg src" in result.stdout
    assert "pg ops" in result.stdout
    assert "未配置" in result.stdout
    assert "migrate" in result.stdout


@pytest.mark.unit
def test_db_migrate_without_write_db_does_not_write() -> None:
    result = runner.invoke(app, ["db", "migrate"])
    assert result.exit_code == 1, result.output
    assert "未配置" in result.output or "拒绝写库" in result.output


@pytest.mark.unit
def test_db_migrate_help_lists_write_db() -> None:
    result = runner.invoke(app, ["db", "migrate", "--help"])
    assert result.exit_code == 0
    assert "--write-db" in result.stdout
    assert "--plane" in result.stdout


@pytest.mark.unit
def test_root_help_lists_check_and_db() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "check" in result.stdout
    assert "db" in result.stdout
