"""domain.ports：读取接口的 Protocol 定义。

负责：用领域语言表达的仓储接口，如 ``CalendarRepository``、
``UniverseRepository``、``PriceRepository``、``FundamentalRepository``、
``FeatureRepository``。

接口签名只出现领域概念（``as_of``、``universe_id``、``asset_id``、
``event_dt``），**不得出现 SQL 片段、表名、schema 名或文件路径**。判断标准：
把底层从 PostgreSQL 换成 Parquet，接口签名不应有任何变化。

不负责：任何实现。实现在 ``quantagent.adapters``。

职责定义见 ``docs/architecture/ports-and-adapters.md``。
"""

__all__: list[str] = []
