"""打开 ``wind_db`` 只读连接。凭据来自 Settings，驱动按需 import。"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from quantagent.platform.errors import ConfigError

if TYPE_CHECKING:
    from quantagent.platform.config.settings import Settings


def open_wind_connection(settings: Settings) -> Any:
    if not settings.wind_mssql_configured:
        raise ConfigError(
            "Wind SQL Server 未配置：需要 QUANTAGENT_WIND_MSSQL_HOST 与 QUANTAGENT_WIND_MSSQL_USER"
        )
    try:
        pymssql = import_module("pymssql")
    except ImportError as exc:
        raise ConfigError("未安装 pymssql，请安装 sources 依赖组") from exc
    return pymssql.connect(
        server=settings.wind_mssql_host,
        port=str(settings.wind_mssql_port),
        user=settings.wind_mssql_user,
        password=settings.wind_mssql_password.get_secret_value(),
        database=settings.wind_mssql_database,
        login_timeout=15,
        timeout=120,
    )
