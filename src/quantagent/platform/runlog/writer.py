"""把 run log 落成 JSON。已有同名文件即失败——运行身份不得复用。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.platform.errors import RunLogError

if TYPE_CHECKING:
    from pathlib import Path

    from quantagent.platform.runlog.record import RunLog
    from quantagent.platform.storage.paths import VarPaths


def persist_run_log(record: RunLog, paths: VarPaths) -> Path:
    paths.runs.mkdir(parents=True, exist_ok=True)
    dest = paths.runs / f"{record.run_id}.json"
    if dest.exists():
        raise RunLogError(f"run log 已存在，拒绝覆盖: {dest.name}")
    dest.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return dest
