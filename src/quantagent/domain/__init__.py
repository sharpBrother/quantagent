"""domain：口径规则，零存储依赖。

负责：交易日历与频率对齐、复权规则、资产身份（代码映射、上市退市生命
周期、代码复用消歧）、可见性规则求解（PIT）、股票池构造、行业与风格
分类口径。以及 ``domain.ports`` 下的读取接口 Protocol。

**硬约束：不得 import 任何 PostgreSQL、DuckDB、Parquet、pandas IO 相关
内容。** 这一层必须能在没有数据库和任何文件的情况下完整单测——旧仓的
``BaseDataGateway`` 自身 ``from dbconnect import DBConnect``，把规则和传输
绑死，这是要避免的反例。

不负责：连接、分块、重试、谓词下推、文件布局。这些属于 ``adapters``。

允许依赖：``contracts``。

职责定义见 ``docs/architecture/layers/domain.md``，端口设计见
``docs/architecture/ports-and-adapters.md``。
"""

__all__: list[str] = []
