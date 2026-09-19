"""Wind 中文字段的 latin1→gbk 修复。与旧仓 ADR-0018 同一条，源端编码事故不是口径加工。"""

from __future__ import annotations

from math import isnan
from typing import Any


def decode_chi_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and isnan(value):
        return value
    if not isinstance(value, str):
        return value
    try:
        return value.encode("latin1").decode("gbk")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def decode_chi_row(row: dict[str, object], fields: tuple[str, ...]) -> dict[str, object]:
    if not fields:
        return row
    patched = dict(row)
    for field in fields:
        if field in patched:
            patched[field] = decode_chi_value(patched[field])
    return patched
