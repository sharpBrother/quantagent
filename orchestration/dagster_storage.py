"""把当前 Dagster 存储表形编译成 ``ops`` 上的 CREATE 语句。

不在导入 ``definitions`` 时调用。自建表会跑 alembic，迁移里不能出现 ALTER，
所以表形冻结在编号 SQL 里，实例配置关闭 ``should_autocreate_tables``。
"""

from __future__ import annotations

from dagster._core.storage.event_log import SqlEventLogStorageMetadata
from dagster._core.storage.runs import RunStorageSqlMetadata
from dagster._core.storage.schedules import ScheduleStorageSqlMetadata
from sqlalchemy import MetaData
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.schema import CreateIndex, CreateTable

_DIALECT = dialect()  # type: ignore[no-untyped-call]  # SQLAlchemy 方言构造器无类型注解
_HEADER = """-- Dagster 1.13.22 / dagster-postgres 0.29.22 的当前表形。
-- 运行存储放在 ops。不走自建表：自建会执行 alembic，其中包含 ALTER。
-- 实例配置必须 should_autocreate_tables: false，并且 search_path=ops。
-- 升级 Dagster 若改了表形，不要改本文件；已应用迁移的 checksum 对不上会停。
"""


def dagster_ops_statements() -> tuple[str, ...]:
    """返回不含注释的 CREATE 语句，顺序满足外键。"""
    target = MetaData()
    existing: set[str] = set()
    for source in (
        RunStorageSqlMetadata,
        SqlEventLogStorageMetadata,
        ScheduleStorageSqlMetadata,
    ):
        for table in source.sorted_tables:
            if table.name in existing:
                continue
            table.to_metadata(target, schema="ops")
            existing.add(table.name)
    statements: list[str] = []
    index_names: set[str] = set()
    for table in target.sorted_tables:
        statements.append(str(CreateTable(table).compile(dialect=_DIALECT)).strip())
        for index in sorted(table.indexes, key=lambda item: item.name or ""):
            name = index.name or ""
            if name in index_names:
                raise RuntimeError(f"索引名重复: {name}")
            index_names.add(name)
            statements.append(str(CreateIndex(index).compile(dialect=_DIALECT)).strip())
    return tuple(statements)


def dagster_ops_migration_sql() -> str:
    body = "\n\n".join(f"{statement};" for statement in dagster_ops_statements())
    return f"{_HEADER}\n{body}\n"
