"""源表数据面允许的 SQL 动词。

迁移运行器管结构（CREATE/COMMENT）。这里管 ingest 写入路径：默认只允许
INSERT 与回读用的 SELECT。禁止 UPDATE/MERGE/TRUNCATE/DROP/ALTER 与 UPSERT。
显式 ``--replace-existing`` 才走 ``assert_src_replace_sql``，额外允许
按主键 DELETE，仍禁止 UPDATE/MERGE。
"""

from __future__ import annotations

import re

from quantagent.adapters.postgres.errors import ForbiddenSqlError

_LEADING = re.compile(r"^\s*(INSERT|SELECT)\b", re.IGNORECASE)
_FORBIDDEN = re.compile(
    r"\b(?:UPDATE|MERGE|TRUNCATE|DROP|ALTER|DELETE|GRANT|REVOKE|COPY|ON\s+CONFLICT)\b",
    re.IGNORECASE,
)
_LEADING_REPLACE = re.compile(r"^\s*(DELETE|INSERT|SELECT)\b", re.IGNORECASE)
_FORBIDDEN_REPLACE = re.compile(
    r"\b(?:UPDATE|MERGE|TRUNCATE|DROP|ALTER|GRANT|REVOKE|COPY|ON\s+CONFLICT)\b",
    re.IGNORECASE,
)


def assert_src_dml_sql(statement: str) -> str:
    """语句非法时抛 ``ForbiddenSqlError``，不得改写后放行。"""
    if not statement or not statement.strip():
        raise ForbiddenSqlError("空 SQL")
    if _LEADING.search(statement) is None:
        leading = statement.strip().split(None, 1)[0]
        raise ForbiddenSqlError(f"源表 DML 动词非法: {leading}")
    forbidden = _FORBIDDEN.search(statement)
    if forbidden is not None:
        raise ForbiddenSqlError(f"源表 DML 含禁止动词: {forbidden.group(0)}")
    return statement


def assert_src_replace_sql(statement: str) -> str:
    """仅供显式 --replace-existing：允许 DELETE + INSERT，仍禁止 UPDATE/MERGE。"""
    if not statement or not statement.strip():
        raise ForbiddenSqlError("空 SQL")
    if _LEADING_REPLACE.search(statement) is None:
        leading = statement.strip().split(None, 1)[0]
        raise ForbiddenSqlError(f"源表替换 DML 动词非法: {leading}")
    forbidden = _FORBIDDEN_REPLACE.search(statement)
    if forbidden is not None:
        raise ForbiddenSqlError(f"源表替换 DML 含禁止动词: {forbidden.group(0)}")
    return statement
