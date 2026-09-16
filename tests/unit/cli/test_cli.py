"""CLI 入口：check contracts 与 db status。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from quantagent.cli.app import app
from quantagent.platform.config import cache_clear

if TYPE_CHECKING:
    from collections.abc import Generator

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clear_settings() -> Generator[None, None, None]:
    cache_clear()
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


@pytest.mark.unit
def test_root_help_lists_check_and_db() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "check" in result.stdout
    assert "db" in result.stdout
