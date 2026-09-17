"""platform 配置与写闸。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from quantagent.platform.config import Settings, assert_db_write_allowed, cache_clear, get_settings
from quantagent.platform.errors import WriteGateError

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Generator[None, None, None]:
    cache_clear()
    yield
    cache_clear()


@pytest.mark.unit
def test_write_gate_requires_cli_flag() -> None:
    settings = Settings(_env_file=None, allow_db_write=True)
    with pytest.raises(WriteGateError, match="--write-db"):
        assert_db_write_allowed(settings=settings, write_db=False)


@pytest.mark.unit
def test_write_gate_requires_env_flag() -> None:
    settings = Settings(_env_file=None, allow_db_write=False)
    with pytest.raises(WriteGateError, match="QUANTAGENT_ALLOW_DB_WRITE"):
        assert_db_write_allowed(settings=settings, write_db=True)


@pytest.mark.unit
def test_write_gate_opens_only_when_both_true() -> None:
    settings = Settings(_env_file=None, allow_db_write=True)
    assert_db_write_allowed(settings=settings, write_db=True)


@pytest.mark.unit
def test_pg_configured_requires_database_and_user() -> None:
    blank = Settings(_env_file=None)
    assert blank.pg_src_configured is False
    filled = Settings(_env_file=None, pg_src_database="quantagent", pg_src_user="qa")
    assert filled.pg_src_configured is True


@pytest.mark.unit
def test_get_settings_reads_profile_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTAGENT_PROFILE", "office")
    cache_clear()
    assert get_settings().profile == "office"


@pytest.mark.unit
def test_allow_db_write_defaults_false() -> None:
    assert Settings(_env_file=None).allow_db_write is False


@pytest.mark.unit
def test_tushare_token_defaults_empty() -> None:
    settings = Settings(_env_file=None)
    assert settings.tushare_token.get_secret_value() == ""
