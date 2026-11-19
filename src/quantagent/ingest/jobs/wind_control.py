"""初始化作业按运行 ID 请求在已提交页之后停止。"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from pathlib import Path

    from quantagent.platform.storage.paths import VarPaths


def wind_stop_path(paths: VarPaths, run_id: str) -> Path:
    # 运行 ID 必须是规范 UUID，既隔离其他运行，也避免输入变成任意文件路径。
    parsed = UUID(run_id)
    if str(parsed) != run_id:
        raise ValueError("run ID 必须是小写、带连字符的 UUID")
    return paths.logs / "wind_ingest_progress" / f"{run_id}.stop"
