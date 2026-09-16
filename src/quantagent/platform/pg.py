"""PostgreSQL 连接工厂。全仓库唯一从 Settings 拼 DSN 的地方。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import psycopg
from psycopg.conninfo import make_conninfo

from quantagent.platform.errors import ConfigError

if TYPE_CHECKING:
    from quantagent.platform.config.settings import Settings

Plane = Literal["src", "ops"]


def dsn_for(settings: Settings, plane: Plane) -> str:
    """按面返回连接串。未配置 fail-closed，不返回半成品 DSN。"""
    if plane == "src":
        if not settings.pg_src_configured:
            raise ConfigError(
                "PostgreSQL 研究数据面未配置：需要 QUANTAGENT_PG_SRC_DATABASE 与 QUANTAGENT_PG_SRC_USER"
            )
        return make_conninfo(
            host=settings.pg_src_host,
            port=settings.pg_src_port,
            dbname=settings.pg_src_database,
            user=settings.pg_src_user,
            password=settings.pg_src_password.get_secret_value(),
        )
    if not settings.pg_ops_configured:
        raise ConfigError(
            "PostgreSQL 控制状态面未配置：需要 QUANTAGENT_PG_OPS_DATABASE 与 QUANTAGENT_PG_OPS_USER"
        )
    return make_conninfo(
        host=settings.pg_ops_host,
        port=settings.pg_ops_port,
        dbname=settings.pg_ops_database,
        user=settings.pg_ops_user,
        password=settings.pg_ops_password.get_secret_value(),
    )


def connect(settings: Settings, plane: Plane) -> psycopg.Connection[Any]:
    """打开连接。调用方负责关闭；默认关闭自动提交，DDL 与登记同一事务。"""
    return psycopg.connect(dsn_for(settings, plane))


def plane_configured(settings: Settings, plane: Plane) -> bool:
    if plane == "src":
        return settings.pg_src_configured
    return settings.pg_ops_configured
