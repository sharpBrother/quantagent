"""lake：Parquet Lakehouse 的物化与读取。

负责：把 PG ``src_*`` 物化为 ``std``（标准化：统一资产标识、单位、字段
命名与类型），再对齐口径物化为 ``mart``（可分析事实表）；分区布局、文件
大小控制、排序键、compaction；DuckDB 读取入口。

不负责：因子计算（``features``）、模型（``models``）、信号（``strategy``）。
也不负责业务口径的定义——口径来自 ``domain``，本层只执行。

允许依赖：``platform``、``contracts``、``domain``、``adapters``。

物理布局的分区键、目标文件大小、排序键与压缩参数以 benchmark 结论 ADR
为准，见 ``docs/architecture/feature-storage.md``。

职责定义见 ``docs/architecture/layers/lake.md``。
"""

__all__: list[str] = []
