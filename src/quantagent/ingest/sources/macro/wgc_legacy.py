"""只读旧库 WGC 表；保留原始字段，不推断历史版本。"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from quantagent.adapters.postgres.src_targets import WGC_GOLD_DEMAND
from quantagent.platform.errors import ConfigError

if TYPE_CHECKING:
    from quantagent.platform.config.settings import Settings


def read_wgc_legacy(settings: Settings) -> list[dict[str, object]]:
    """整表读取以便原样迁移；来源固定，不接受运行时表名。"""
    if not settings.legacy_mssql_configured:
        raise ConfigError("wx2 未配置 legacy SQL Server 连接")
    pymssql = import_module("pymssql")
    conn = pymssql.connect(
        server=settings.legacy_mssql_host,
        port=str(settings.legacy_mssql_port),
        user=settings.legacy_mssql_user,
        password=settings.legacy_mssql_password.get_secret_value(),
        database=settings.legacy_mssql_database,
        tds_version="7.0",
        login_timeout=15,
        timeout=120,
    )
    try:
        with conn.cursor(as_dict=True) as cur:
            cur.execute(
                "SELECT period_end, geography, category, value_tonnes, publish_date, "
                "source, file_sha256, record_hash, ingested_at "
                "FROM dbo.macro_wgc_gold_demand ORDER BY record_hash"
            )
            return [
                {column: row[column] for column in WGC_GOLD_DEMAND.native_columns} for row in cur
            ]
    finally:
        conn.close()
