"""quantagent/adapters/postgres

PostgreSQL 研究数据面 ``src_*`` 与控制状态面 ``ops_*`` 的适配器。
P1 这一刀先提供双面迁移运行器；源表读取端口随后续切片补齐。

职责定义见 docs/architecture/layers/adapters.md。
"""

from quantagent.adapters.postgres.errors import MigrationError, PostgresAdapterError
from quantagent.adapters.postgres.migrate import apply_migrations, collect_status

__all__ = [
    "MigrationError",
    "PostgresAdapterError",
    "apply_migrations",
    "collect_status",
]
