"""采集失败。口径错误不放这里——源端给了什么，这里只负责忠实地写入或拒绝。"""

from __future__ import annotations


class IngestError(Exception):
    """采集失败的基类。"""


class TargetNotAllowedError(IngestError):
    """目标表不在写入白名单，或命中显式禁写名单。"""


class DuplicateKeyError(IngestError):
    """载荷内主键重复，或目标表已有相同键。不覆盖既有行。"""


class EmptyPayloadError(IngestError):
    """源端返回空集。缺失就是缺失，但交易日历空窗是采集失败，不是合法空表。"""


class ReadbackError(IngestError):
    """同一事务内回读的行数或 digest 与写入不一致。"""


class ReplaceRequiredError(IngestError):
    """目标键已存在且内容变了，或源端 OPMODE=2。必须显式 --replace-existing。"""


class SourceFetchError(IngestError):
    """源端拉取失败，或返回了无法按原生口径解释的值。"""
