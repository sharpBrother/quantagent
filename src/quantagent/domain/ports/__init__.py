"""domain.ports：读取接口的 Protocol 定义。

负责：用领域语言表达的仓储接口。接口签名只出现领域概念（``as_of``、
``exchange``、``cal_dt``），不得出现 SQL、表名或文件路径。

不负责：任何实现。实现在 ``quantagent.adapters``。
"""

from quantagent.domain.ports.calendar import CalendarRepository
from quantagent.domain.ports.feature import FeatureRepository
from quantagent.domain.ports.feature_metric import FeatureMetricRepository
from quantagent.domain.ports.forward_return import ForwardReturnRepository
from quantagent.domain.ports.group_nav import GroupNavRepository
from quantagent.domain.ports.universe import UniverseRepository

__all__ = [
    "CalendarRepository",
    "FeatureMetricRepository",
    "FeatureRepository",
    "ForwardReturnRepository",
    "GroupNavRepository",
    "UniverseRepository",
]
