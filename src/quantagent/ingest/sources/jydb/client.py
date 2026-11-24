"""打开 ``JYDB`` 只读连接。凭据只来自 Settings，驱动按需导入。

旧仓 ``[jy2]`` 与 wx2 使用 TDS 7.0；配置保留 ``jydb_mssql_tds_version``，由源端
支持情况决定。连接失败直接抛出，不由采集层重试或猜测。
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from quantagent.platform.errors import ConfigError

if TYPE_CHECKING:
    from quantagent.platform.config.settings import Settings


def open_jydb_connection(settings: Settings) -> Any:
    if not settings.jydb_mssql_configured:
        raise ConfigError("JYDB 未配置：需要 QUANTAGENT_JYDB_MSSQL_HOST、DATABASE 与 USER")
    try:
        pymssql = import_module("pymssql")
    except ImportError as exc:
        raise ConfigError("未安装 pymssql，请安装 sources 依赖组") from exc
    return pymssql.connect(
        server=settings.jydb_mssql_host,
        port=str(settings.jydb_mssql_port),
        user=settings.jydb_mssql_user,
        password=settings.jydb_mssql_password.get_secret_value(),
        database=settings.jydb_mssql_database,
        tds_version=settings.jydb_mssql_tds_version,
        login_timeout=15,
        timeout=120,
    )
