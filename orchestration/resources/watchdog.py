"""采集子进程看门狗的向后兼容 re-export。

唯一事实源在 ``quantagent.ingest.watchdog``——CLI 与 Dagster 资产都需要看门狗，
而 CLI 不能反向依赖 orchestration，故机制下沉到 ingest 层。本模块保留只为不破坏
既有 import 路径（``orchestration.resources.wind``、``jydb``、``suntime`` 与对应测试）。
新代码一律从 ``quantagent.ingest.watchdog`` 导入。
"""

from __future__ import annotations

from quantagent.ingest.watchdog import (
    DEFAULT_STALL_SECONDS,
    POLL_SECONDS,
    TERM_GRACE_SECONDS,
    PageProgress,
    last_progress_time,
    run_watched_child,
    stop_child,
)

__all__ = [
    "DEFAULT_STALL_SECONDS",
    "POLL_SECONDS",
    "TERM_GRACE_SECONDS",
    "PageProgress",
    "last_progress_time",
    "run_watched_child",
    "stop_child",
]
