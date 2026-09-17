"""ingest：外部源到 PG 研究数据面的采集。

负责：从 Wind、Tushare、聚源 JYDB、朝阳永续、宏观数据源拉取数据，写入
PG ``src_*`` schema 的源原生表；批次登记写入 ``src_<source>._batch``。
原始拉取不另存第二份源镜像。

**这是全仓库唯一允许写 PG 研究数据面的层。**

硬约束：
- 源表字段名、类型、语义与源端严格一致，不改含义、不加业务字段；
  系统侧信息只走 ``_batch_id`` / ``_ingested_at`` / ``_row_hash`` 技术元数据列。
- 不做任何业务加工。标准化属于 ``lake`` 的 std 层。
- 写库默认关闭，必须显式开启；目标表白名单写死在代码常量里；
  insert-only，不覆盖既有行，写后回读校验。见 ``AGENTS.md``。

不负责：派生计算、口径对齐、PIT 判定。

允许依赖：``platform``、``contracts``、``adapters``。

职责定义见 ``docs/architecture/layers/ingest.md``。
"""

__all__: list[str] = []
