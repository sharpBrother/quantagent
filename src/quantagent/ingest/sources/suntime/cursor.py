"""朝阳永续分页游标 ``(tmstamp, id)``。

源端按同步序列 ``tmstamp`` 递增发布，同一次同步内再按主键 ``id`` 排序。游标只
表示“已经处理到哪里”，与 ``_ingested_at`` 无关；提交成功后才推进。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from quantagent.ingest.errors import SourceFetchError

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class SuntimeCursor:
    tmstamp: int
    id: int

    def encode(self) -> str:
        return json.dumps({"tmstamp": self.tmstamp, "id": self.id}, separators=(",", ":"))


def initial_cursor() -> SuntimeCursor:
    # tmstamp 与 id 都是正数；-1 让首条记录也满足严格大于条件。
    return SuntimeCursor(tmstamp=-1, id=-1)


def cursor_from_row(row: Mapping[str, object]) -> SuntimeCursor:
    return SuntimeCursor(
        tmstamp=_as_int(row.get("tmstamp"), "tmstamp"),
        id=_as_int(row.get("id"), "id"),
    )


def decode_cursor(value: str | None) -> SuntimeCursor:
    if value is None:
        return initial_cursor()
    try:
        raw = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SourceFetchError(f"朝阳永续游标不是合法 JSON: {value!r}") from exc
    if not isinstance(raw, dict) or set(raw) != {"tmstamp", "id"}:
        raise SourceFetchError(f"朝阳永续游标形状不符: {value!r}")
    return SuntimeCursor(
        tmstamp=_as_int(raw["tmstamp"], "tmstamp"),
        id=_as_int(raw["id"], "id"),
    )


def _as_int(value: object, name: str) -> int:
    # bool 是 int 子类，不能把 True 当游标。pymssql 会把 bigint 读成 Decimal。
    if isinstance(value, bool):
        raise SourceFetchError(f"朝阳永续游标字段 {name} 不是整数: {value!r}")
    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise SourceFetchError(f"朝阳永续游标字段 {name} 不是整数: {value!r}")
        return int(value)
    if not isinstance(value, int):
        raise SourceFetchError(f"朝阳永续游标字段 {name} 不是整数: {value!r}")
    return value
