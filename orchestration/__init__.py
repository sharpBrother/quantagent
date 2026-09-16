"""orchestration：Dagster 资产化编排，也是一个 composition root。

负责：把数据层与计算层表达为 Dagster asset（含分区与依赖）、job、
schedule、sensor；在 ``resources/`` 完成适配器注入；运行状态落 PG
``ops_*`` 控制状态面。

选择资产化编排而非流程编排，是因为本项目的真实痛点是血缘不可见、分区
回填困难、物化状态无处记录——资产模型直接对上这三条。

允许依赖：全部层（composition root 的特权）。反之业务层不得依赖本包。

见 ``docs/architecture/cli-and-orchestration.md``。
"""

__all__: list[str] = []
