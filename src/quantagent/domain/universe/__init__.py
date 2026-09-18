"""股票池成员区间规则。仓储只取行；命中区间在这里算。"""

from quantagent.domain.universe.interval import interval_contains
from quantagent.domain.universe.member import UniverseMember

__all__ = ["UniverseMember", "interval_contains"]
