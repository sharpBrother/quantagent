"""PostgreSQL 适配器失败。"""

from __future__ import annotations


class PostgresAdapterError(Exception):
    """适配器侧失败的基类。"""


class MigrationError(PostgresAdapterError):
    """迁移文件非法、校验和不匹配、或执行失败。"""


class ForbiddenSqlError(PostgresAdapterError):
    """源表写入路径出现了 insert-only 白名单以外的 SQL 动词。"""


class TransactionUnknownError(PostgresAdapterError):
    """提交或回滚结果不确定。调用方必须停下报告，不得重试。"""


class SrcConflictError(PostgresAdapterError):
    """插入时撞上已有主键或其他完整性约束。"""
