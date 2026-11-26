"""打开 ``suntime_db`` 只读连接。凭据只来自 Settings，驱动按需导入。

2026-11-24 源库核对：SQL Server 2014，``charset="utf8"`` 直接读出正确中文，
不再做旧仓那套 latin1 再解 GBK。解码失败由驱动抛出，采集停下，不把字段置空。
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from quantagent.platform.errors import ConfigError

if TYPE_CHECKING:
    from quantagent.platform.config.settings import Settings


def open_suntime_connection(settings: Settings) -> Any:
    if not settings.suntime_mssql_configured:
        raise ConfigError("朝阳永续未配置：需要 QUANTAGENT_SUNTIME_MSSQL_HOST、DATABASE 与 USER")
    try:
        pymssql = import_module("pymssql")
    except ImportError as exc:
        raise ConfigError("未安装 pymssql，请安装 sources 依赖组") from exc
    return pymssql.connect(
        server=settings.suntime_mssql_host,
        port=str(settings.suntime_mssql_port),
        user=settings.suntime_mssql_user,
        password=settings.suntime_mssql_password.get_secret_value(),
        database=settings.suntime_mssql_database,
        tds_version=settings.suntime_mssql_tds_version,
        charset=settings.suntime_mssql_charset,
        login_timeout=15,
        timeout=120,
    )
