"""platform：技术基础设施。

负责：配置解析与环境切换、结构化日志、运行记录（run log）、身份与
digest 计算、对象存储与本地路径解析、PostgreSQL 连接工厂、DuckDB 会话管理。

**这是全仓库唯一允许接触连接串与凭据的地方。**

不负责：任何业务口径、任何数据语义、任何 SQL 语句的业务含义。

允许依赖：标准库与第三方库。不得 import 本仓库其他层。

职责定义见 ``docs/architecture/layers/platform.md``。
"""

__all__: list[str] = []
