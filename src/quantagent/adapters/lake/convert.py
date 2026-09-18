"""湖读取共用的类型转换。缺失不得补 0。"""

from __future__ import annotations

from datetime import date, datetime
from math import isnan
from numbers import Integral

from quantagent.domain.errors import InvalidQueryError


def as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise InvalidQueryError(f"无法转为 date: {value!r}")


def as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    raise InvalidQueryError(f"无法转为 datetime: {value!r}")


def as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise InvalidQueryError(f"无法转为 int: {value!r}")
    return int(value)


def require_float(value: object) -> float:
    if value is None:
        raise InvalidQueryError("数值缺失，不得补 0")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidQueryError(f"无法转为 float: {value!r}")
    number = float(value)
    if isnan(number):
        raise InvalidQueryError("数值缺失，不得补 0")
    return number
