"""DuckDB 会话管理。

负责：创建纯内存会话、挂载 Parquet、设置内存与线程。
不负责：表名语义、PIT 过滤、分区键选择。
"""

from quantagent.platform.duck.session import (
    assert_ident,
    duck_session,
    open_session,
    register_parquet,
)

__all__ = [
    "assert_ident",
    "duck_session",
    "open_session",
    "register_parquet",
]
