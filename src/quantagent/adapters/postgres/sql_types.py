"""SQL Server 源类型到 PostgreSQL 的机械映射。

只做类型对应，不改含义、不改精度。SQL Server ``timestamp`` / ``rowversion``
是二进制版本号，不是时间——映射到 ``bytea``，避免被当成 ``timestamptz``
后污染 PIT。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

_VARCHAR_MAX = re.compile(r"^(?:n)?varchar\s*\(\s*max\s*\)$", re.IGNORECASE)
_NATIONAL_CHAR = re.compile(r"^n(varchar|char)\s*(\(.*\))$", re.IGNORECASE)
_DATETIME2 = re.compile(r"^datetime2(?:\s*\(\s*\d+\s*\))?$", re.IGNORECASE)
_NUMERIC = re.compile(r"^(numeric|decimal|dec)\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)$", re.IGNORECASE)
_CHAR = re.compile(r"^(var)?char\s*\(\s*(\d+)\s*\)$", re.IGNORECASE)

_SIMPLE = {
    "timestamp": "bytea",
    "rowversion": "bytea",
    "datetime": "timestamp",
    "smalldatetime": "timestamp",
    "date": "date",
    "float": "double precision",
    "real": "real",
    "smallfloat": "real",
    "int": "integer",
    "bigint": "bigint",
    "smallint": "smallint",
    "tinyint": "smallint",
    "bit": "boolean",
    "money": "numeric(19, 4)",
    "text": "text",
    "ntext": "text",
    "xml": "text",
}

_PATTERN_RENDERERS: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], str]], ...] = (
    (_DATETIME2, lambda _match: "timestamp"),
    (_VARCHAR_MAX, lambda _match: "text"),
    (_NUMERIC, lambda match: f"numeric({match.group(2)}, {match.group(3)})"),
    (_NATIONAL_CHAR, lambda match: f"varchar{match.group(2)}"),
    (
        _CHAR,
        lambda match: f"{'varchar' if match.group(1) else 'char'}({match.group(2)})",
    ),
)


def map_sql_server_type(raw: str) -> str:
    """把数据字典里的 SQL Server 类型写成 PostgreSQL 类型。未知类型 fail-closed。"""
    text = " ".join(raw.strip().split())
    mapped = _map_known(text) if text else None
    if mapped is None:
        msg = f"未映射的 SQL Server 类型: {raw}" if text else "字段类型为空"
        raise ValueError(msg)
    return mapped


def quote_ident(name: str) -> str:
    """PostgreSQL 标识符引用，保留源端大小写。"""
    if not name or name != name.strip():
        msg = f"非法标识符: {name!r}"
        raise ValueError(msg)
    return '"' + name.replace('"', '""') + '"'


def _map_known(text: str) -> str | None:
    simple = _SIMPLE.get(text.lower())
    if simple is not None:
        return simple
    for pattern, renderer in _PATTERN_RENDERERS:
        matched = pattern.fullmatch(text)
        if matched is not None:
            return renderer(matched)
    return None
