"""第一批 ``src_*`` 表清单。清单在 ``db/src_tables.yaml``，这里只负责加载。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import yaml

from quantagent.adapters.postgres.errors import MigrationError

if TYPE_CHECKING:
    from pathlib import Path

DICT_FOLDER_BY_SOURCE = {
    "wind": "wind",
    "tushare": "tushare",
    "jydb": "jy",
    "suntime": "suntime",
}


@dataclass(frozen=True)
class SrcTable:
    source: str
    schema: str
    name: str


def load_src_tables(repo_root: Path) -> tuple[SrcTable, ...]:
    path = repo_root / "db" / "src_tables.yaml"
    if not path.is_file():
        raise MigrationError(f"找不到源表清单: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise MigrationError("db/src_tables.yaml 必须是映射")
    schemas = raw.get("schemas")
    tables = raw.get("tables")
    if not isinstance(schemas, dict) or not isinstance(tables, list):
        raise MigrationError("db/src_tables.yaml 缺少 schemas 或 tables")
    schema_by_source = _require_str_map(schemas)
    loaded: list[SrcTable] = []
    seen: set[tuple[str, str]] = set()
    for item in tables:
        if not isinstance(item, dict):
            raise MigrationError("tables 项必须是映射")
        source = _require_str(item.get("source"), "source")
        name = _require_str(item.get("name"), "name")
        schema = schema_by_source.get(source)
        if schema is None:
            raise MigrationError(f"未知 source: {source}")
        key = (schema, name)
        if key in seen:
            raise MigrationError(f"重复表: {schema}.{name}")
        seen.add(key)
        loaded.append(SrcTable(source=source, schema=schema, name=name))
    if not loaded:
        raise MigrationError("db/src_tables.yaml 的 tables 为空")
    return tuple(loaded)


def schema_names(tables: tuple[SrcTable, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(table.schema for table in tables))


def _require_str_map(raw: dict[Any, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str) or not key or not value:
            raise MigrationError("schemas 必须是非空字符串到非空字符串")
        out[key] = value
    return out


def _require_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise MigrationError(f"{field} 必须是非空字符串")
    return value
