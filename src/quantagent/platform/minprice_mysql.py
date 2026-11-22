"""分钟行情 MySQL 只读连接；连接配置只能在 platform 层使用。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from quantagent.platform.errors import ConfigError

if TYPE_CHECKING:
    from quantagent.platform.config import Settings


def connect_minprice(settings: Settings) -> Any:
    """建立只读事务，避免采集进程误写旧源。"""
    import pymysql  # type: ignore[import-untyped]  # noqa: PLC0415

    if not settings.minprice_mysql_host or not settings.minprice_mysql_user:
        raise ConfigError("分钟行情 MySQL 未配置 host 或 user")
    conn = pymysql.connect(
        host=settings.minprice_mysql_host,
        port=settings.minprice_mysql_port,
        database=settings.minprice_mysql_database,
        user=settings.minprice_mysql_user,
        password=settings.minprice_mysql_password.get_secret_value(),
        cursorclass=pymysql.cursors.SSCursor,
        autocommit=False,
        connect_timeout=10,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
    except BaseException:
        conn.close()
        raise
    return conn
