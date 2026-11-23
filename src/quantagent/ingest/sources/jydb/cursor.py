"""聚源分页游标 ``(JSID, ID)``。

源端按同步序列 ``JSID`` 递增发布，同一次同步内再按主键 ``ID`` 排序。游标只
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
class JydbCursor:
    jsid: int
    id: int

    def encode(self) -> str:
        return json.dumps({"jsid": self.jsid, "id": self.id}, separators=(",", ":"))


def initial_cursor() -> JydbCursor:
    # JSID 与 ID 都是正数；-1 让首条记录也满足严格大于条件。
    return JydbCursor(jsid=-1, id=-1)


def cursor_from_row(row: Mapping[str, object]) -> JydbCursor:
    return JydbCursor(jsid=_as_int(row.get("JSID"), "JSID"), id=_as_int(row.get("ID"), "ID"))


def decode_cursor(value: str | None) -> JydbCursor:
    if value is None:
        return initial_cursor()
    try:
        raw = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SourceFetchError(f"聚源游标不是合法 JSON: {value!r}") from exc
    if not isinstance(raw, dict) or set(raw) != {"jsid", "id"}:
        raise SourceFetchError(f"聚源游标形状不符: {value!r}")
    return JydbCursor(jsid=_as_int(raw["jsid"], "jsid"), id=_as_int(raw["id"], "id"))


def _as_int(value: object, name: str) -> int:
    # bool 是 int 子类，不能把 True 当游标。pymssql 会把 bigint 读成 Decimal。
    if isinstance(value, bool):
        raise SourceFetchError(f"聚源游标字段 {name} 不是整数: {value!r}")
    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise SourceFetchError(f"聚源游标字段 {name} 不是整数: {value!r}")
        return int(value)
    if not isinstance(value, int):
        raise SourceFetchError(f"聚源游标字段 {name} 不是整数: {value!r}")
    return value
