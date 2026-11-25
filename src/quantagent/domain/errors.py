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


class PriceLookupError(DomainError):
    """行情行缺失键、日期非法，或同一交易日同一代码出现多行。"""


class MoneyFlowLookupError(DomainError):
    """资金流读取到的数据不满足键或格式约束。"""


class DerivativeIndicatorLookupError(DomainError):
    """衍生指标读取到的数据不满足键或格式约束。"""


class MacroLookupError(DomainError):
    """宏观观测缺键、日期非法，或同一观测有多个同时生效的版本。"""


class IncrementError(DomainError):
    """日更增量无法判定：lake 没有历史、开市日历不足以判定就绪、区间参数不合法。fail-closed。"""
