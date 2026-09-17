"""quantagent/ingest/writers

源表 insert-only 写入。六条铁律见 ``src_insert.write_src_snapshot``。
"""

from quantagent.ingest.writers.src_insert import SrcWriteResult, write_src_snapshot
from quantagent.ingest.writers.tables import (
    ALLOWED_SRC_WRITE_TARGETS,
    FORBIDDEN_SRC_WRITE_TARGETS,
    TRADE_CAL,
    SrcTableWriteSpec,
    assert_writable,
)

__all__ = [
    "ALLOWED_SRC_WRITE_TARGETS",
    "FORBIDDEN_SRC_WRITE_TARGETS",
    "TRADE_CAL",
    "SrcTableWriteSpec",
    "SrcWriteResult",
    "assert_writable",
    "write_src_snapshot",
]
