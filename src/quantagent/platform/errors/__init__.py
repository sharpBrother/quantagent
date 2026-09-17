"""platform 层异常。

业务口径错误不属于这里——那些归 ``domain``。这里只表达「配置不成立」
「写闸未开」「路径无法解析」这类基础设施失败。
"""

from __future__ import annotations


class PlatformError(Exception):
    """platform 层失败的基类。"""


class ConfigError(PlatformError):
    """配置缺失、档位非法、或找不到仓库根。"""


class WriteGateError(PlatformError):
    """写库总闸未同时满足环境变量与 ``--write-db``。"""


class RunLogError(PlatformError):
    """运行记录无法落盘，或试图覆盖已有 run log。"""


class DuckSessionError(PlatformError):
    """DuckDB 会话无法创建、挂载失败，或试图持久化 ``.duckdb``。"""
