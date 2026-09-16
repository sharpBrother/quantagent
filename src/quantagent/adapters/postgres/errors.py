"""PostgreSQL 适配器失败。"""

from __future__ import annotations


class PostgresAdapterError(Exception):
    """适配器侧失败的基类。"""


class MigrationError(PostgresAdapterError):
    """迁移文件非法、校验和不匹配、或执行失败。"""
