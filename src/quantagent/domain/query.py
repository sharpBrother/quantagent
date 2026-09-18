"""读取参数校验。空身份与颠倒窗口都 fail-closed，不猜全市场。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.domain.errors import InvalidQueryError

if TYPE_CHECKING:
    from datetime import date


def require_text(*values: str) -> None:
    if any(not value.strip() for value in values):
        raise InvalidQueryError("查询身份字段为空")


def require_window(start: date, end: date) -> None:
    if start > end:
        raise InvalidQueryError("start 晚于 end")
