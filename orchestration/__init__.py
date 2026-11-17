"""orchestration：Dagster 资产化编排，也是一个 composition root。

负责：把数据层与计算层表达为 Dagster asset（含分区与依赖）、job、
schedule、sensor；在 ``resources/`` 完成适配器注入；运行状态落 PG
``ops_*`` 控制状态面。

选择资产化编排而非流程编排，是因为本项目的真实痛点是血缘不可见、分区
回填困难、物化状态无处记录——资产模型直接对上这三条。

允许依赖：全部层（composition root 的特权）。反之业务层不得依赖本包。

见 ``docs/architecture/cli-and-orchestration.md``。

导入期要轻：``dagster-daemon`` 启动代码服务器后只等 20 秒心跳
（``DAEMON_GRPC_SERVER_HEARTBEAT_TTL``），导入 ``orchestration.definitions`` 超时
代码位置就加载失败，调度不会注册。执行机上原先导入要 25–30 秒。因此业务实现
（pandas、pyarrow、duckdb、pandera、pymssql 等）一律在资产、资源、调度函数体内导入，
模块顶层只放 Dagster 定义与轻量常量；测试会拦截回退。
"""

__all__: list[str] = []
