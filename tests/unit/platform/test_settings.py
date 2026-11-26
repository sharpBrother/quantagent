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


@pytest.mark.unit
def test_wind_mssql_configured_requires_host_and_user() -> None:
    blank = Settings(_env_file=None)
    assert blank.wind_mssql_configured is False
    assert blank.wind_mssql_database == "wind_db"
    filled = Settings(_env_file=None, wind_mssql_host="10.0.0.1", wind_mssql_user="wind")
    assert filled.wind_mssql_configured is True


@pytest.mark.unit
def test_jydb_mssql_configured_requires_host_database_and_user() -> None:
    blank = Settings(_env_file=None)
    assert blank.jydb_mssql_configured is False
    assert blank.jydb_mssql_tds_version == "7.0"
    filled = Settings(
        _env_file=None,
        jydb_mssql_host="127.0.0.1",
        jydb_mssql_database="JYDB",
        jydb_mssql_user="reader",
    )
    assert filled.jydb_mssql_configured is True


@pytest.mark.unit
def test_suntime_mssql_configured_requires_host_database_and_user() -> None:
    blank = Settings(_env_file=None)
    assert blank.suntime_mssql_configured is False
    assert blank.suntime_mssql_tds_version == "7.0"
    assert blank.suntime_mssql_charset == "utf8"
    filled = Settings(
        _env_file=None,
        suntime_mssql_host="127.0.0.1",
        suntime_mssql_database="suntime_db",
        suntime_mssql_user="reader",
    )
    assert filled.suntime_mssql_configured is True


def test_legacy_mssql_configured_requires_host_and_user() -> None:
    blank = Settings(_env_file=None)
    assert blank.legacy_mssql_configured is False
    assert blank.legacy_mssql_database == "wx2"
    filled = Settings(_env_file=None, legacy_mssql_host="10.0.0.1", legacy_mssql_user="reader")
    assert filled.legacy_mssql_configured is True
