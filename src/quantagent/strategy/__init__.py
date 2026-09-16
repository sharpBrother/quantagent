"""strategy：信号生成与回测。

负责：策略信号、成本模型、回测执行。

回测的结构是「**一份语义合同 + 多个场景内核**」，不是一个万能引擎：

- ``backtest.contract``：语义合同的类型与校验，是唯一强制共享的部分。
  覆盖信号与执行时间（``signal_dt`` / ``decision_dt`` / ``execution_dt``
  三者分离）、收益与复权与现金与成本、缺价停牌不可交易的处置、输入与
  结果与运行身份。
- ``backtest.vectorized``：向量化截面研究（因子分组收益、IC 序列），无账户。
- ``backtest.rebalance``：组合级再平衡仿真，有账户与成本，不到逐笔。
- ``backtest.event``：事件驱动逐笔模拟，按真实需求决定是否实现。

三类内核输出同一套结果 schema，因此可以互相对照。是否用一个内核替换另
一个，判据是**行为对照测试**（nav / turnover / 持仓序列在容差内一致），
不以文件数减少作为验收标准。

硬约束：缺价不得静默用前值填充。

允许依赖：``platform``、``contracts``、``domain``、``features``、``models``。

见 ``docs/architecture/backtest-contract.md``。
"""

__all__: list[str] = []
