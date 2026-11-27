"""内容身份。

身份算法必须全仓库共用。不同模块各写一套 JSON 序列化，会出现「同一份配置
两个 digest、产物对不上却查不出原因」。
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

_CHUNK = 65536


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_text(text: str) -> str:
    return digest_bytes(text.encode("utf-8"))


def digest_json(obj: Any) -> str:
    """键排序、无空白、UTF-8。键顺序不同必须得到同一 digest。"""
    payload = json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_default,
    )
    return digest_text(payload)


def digest_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _default(obj: Any) -> str:
    if isinstance(obj, Path):
        return obj.as_posix()
    if isinstance(obj, bytes):
        return obj.hex()
    if isinstance(obj, datetime):
        # 带时区的时间统一转 UTC 再序列化。timestamptz 读回的时区表示取决于 server
        # timezone（本机是 Asia/Shanghai），与写入时的 UTC 表示是同一时刻但 isoformat 不同，
        # 会让同一行的指纹在写入与回读时不稳定。规范化到 UTC 后 digest 与时区表示无关。
        if obj.tzinfo is not None:
            return obj.astimezone(UTC).isoformat()
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return format(obj, "f")
    msg = f"无法规范化为 JSON 以计算 digest: {type(obj)!r}"
    raise TypeError(msg)
