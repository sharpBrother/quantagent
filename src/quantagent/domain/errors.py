"""domain 口径失败。空域、不可见、规则未实现都走这里，不猜。"""

from __future__ import annotations


class DomainError(Exception):
    """口径层失败的基类。"""


class EmptyDomainError(DomainError):
    """查询域为空。fail-closed，不回退到全市场或前值。"""


class PitUnsupportedError(DomainError):
    """可见性规则本切片尚未实现。不得假装不可见或全部可见。"""


class MissingVisibilityError(DomainError):
    """没有 visibility 的数据集不得参与任何 PIT 查询。"""


class CalendarLookupError(DomainError):
    """日历行缺失、不可见，或 T+N 超出可见交易日。"""


class FeatureLookupError(DomainError):
    """因子读取参数非法，例如 start 晚于 end。"""


class InvalidQueryError(DomainError):
    """读取参数非法，例如 start 晚于 end 或身份字段为空。"""
