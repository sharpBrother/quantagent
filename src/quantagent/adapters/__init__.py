"""adapters：存储适配器，实现 ``domain.ports`` 的 Protocol。

负责：把领域语言的读取请求翻译成具体存储的访问。连接管理、IN 分块、
死锁重试、谓词下推、分区裁剪这类传输细节全部在这一层。

- ``adapters.postgres``：PG 研究数据面 ``src_*`` 与控制状态面 ``ops_*``
- ``adapters.lake``：Parquet + DuckDB
- ``adapters.memory``：测试用 in-memory fake，让业务层单测不需要任何外部依赖

不负责：业务口径。适配器不得自行决定 PIT 过滤、复权方式或股票池规则——
那些是 ``domain`` 的规则，适配器只按规则给出的参数取数。

允许依赖：``platform``、``contracts``、``domain``（为实现其 Protocol）。

三套适配器必须通过 ``tests/contracts/`` 下同一套端口行为契约测试。

职责定义见 ``docs/architecture/ports-and-adapters.md``。
"""

__all__: list[str] = []
