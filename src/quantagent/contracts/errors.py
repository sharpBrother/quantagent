"""契约层异常。"""

from __future__ import annotations


class ContractError(Exception):
    """契约文件无法解析或结构非法。完整性问题走 CheckReport，不走本异常。"""
