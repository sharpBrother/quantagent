"""运行记录。"""

from quantagent.platform.runlog.record import RunLog
from quantagent.platform.runlog.writer import persist_run_log

__all__ = ["RunLog", "persist_run_log"]
