"""Wind ``OPDATE + OBJECT_ID`` 复合游标。

只记已提交页的末行。``max(OPDATE)`` 会在同一毫秒漏掉后续 OBJECT_ID，这是
旧仓 ``update_stock_daily_paged`` 改成复合键的原因。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from quantagent.ingest.errors import SourceFetchError

INITIAL_OPDATE = datetime(1900, 1, 1)
INITIAL_OBJECT_ID = ""


@dataclass(frozen=True)
class WindCursor:
    opdate: datetime
    object_id: str

    def encode(self) -> str:
        return json.dumps(
            {"opdate": self.opdate.isoformat(), "object_id": self.object_id},
            separators=(",", ":"),
        )


def initial_cursor() -> WindCursor:
    return WindCursor(opdate=INITIAL_OPDATE, object_id=INITIAL_OBJECT_ID)


def decode_cursor(raw: str | None) -> WindCursor:
    if raw is None or raw.strip() == "":
        return initial_cursor()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SourceFetchError(f"Wind 游标无法解析: {raw!r}") from exc
    if not isinstance(payload, dict):
        raise SourceFetchError(f"Wind 游标不是对象: {raw!r}")
    opdate_raw = payload.get("opdate")
    object_id = payload.get("object_id")
    if not isinstance(opdate_raw, str) or not isinstance(object_id, str):
        raise SourceFetchError(f"Wind 游标缺 opdate/object_id: {raw!r}")
    try:
        opdate = datetime.fromisoformat(opdate_raw)
    except ValueError as exc:
        raise SourceFetchError(f"Wind 游标 opdate 非法: {opdate_raw!r}") from exc
    return WindCursor(opdate=opdate, object_id=object_id)


def cursor_from_row(row: dict[str, object]) -> WindCursor:
    opdate = row.get("OPDATE")
    object_id = row.get("OBJECT_ID")
    if not isinstance(opdate, datetime):
        raise SourceFetchError(f"页末 OPDATE 不是 datetime: {type(opdate)!r}")
    if object_id is None:
        raise SourceFetchError("页末 OBJECT_ID 为空")
    return WindCursor(opdate=opdate, object_id=str(object_id))
