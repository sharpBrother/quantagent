"""环境配置。

凭据只从环境变量 / ``.env`` 进入进程，且只允许本模块解析。缺失写库总闸
时默认为关闭——这是数据安全铁律的第一道机械门，不能改成默认开启。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """``QUANTAGENT_*`` 环境变量的唯一入口。"""

    model_config = SettingsConfigDict(
        env_prefix="QUANTAGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    profile: Literal["local", "office"] = "local"
    var_root: Path = Path("var")
    allow_db_write: bool = False

    pg_src_host: str = "127.0.0.1"
    pg_src_port: int = Field(default=5432, ge=1, le=65535)
    pg_src_database: str = ""
    pg_src_user: str = ""
    pg_src_password: SecretStr = SecretStr("")

    pg_ops_host: str = "127.0.0.1"
    pg_ops_port: int = Field(default=5432, ge=1, le=65535)
    pg_ops_database: str = ""
    pg_ops_user: str = ""
    pg_ops_password: SecretStr = SecretStr("")

    tushare_token: SecretStr = SecretStr("")

    wind_mssql_host: str = ""
    wind_mssql_port: int = Field(default=1433, ge=1, le=65535)
    wind_mssql_database: str = "wind_db"
    wind_mssql_user: str = ""
    wind_mssql_password: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def _relative_var_root_only_when_intended(self) -> Self:
        # 绝对路径允许（office 档位可能挂到共享盘）；相对路径必须相对仓库根
        # 解析，禁止在业务代码里再拼。空字符串视为未配置。
        if str(self.var_root).strip() == "":
            msg = "QUANTAGENT_VAR_ROOT 不能为空"
            raise ValueError(msg)
        return self

    @property
    def pg_src_configured(self) -> bool:
        return bool(self.pg_src_database and self.pg_src_user)

    @property
    def pg_ops_configured(self) -> bool:
        return bool(self.pg_ops_database and self.pg_ops_user)

    @property
    def wind_mssql_configured(self) -> bool:
        return bool(self.wind_mssql_host and self.wind_mssql_user)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内缓存。测试必须调用 ``cache_clear``，否则会吃到上一条用例的环境。"""
    return Settings()


def cache_clear() -> None:
    get_settings.cache_clear()
