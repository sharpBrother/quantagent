"""portfolio：组合构建、风险与归因。

负责：权重构建与约束优化、风险度量（波动、暴露、集中度、拥挤度）、
业绩归因。

依赖是分支而非串行：组合风险允许**直读** ``mart`` 的行情与基础信息，加上
自身持仓即可计算，不要求先经过 ``features`` 或 ``strategy``。跨层直读须在
资产契约中声明 ``reads:``，让血缘图可见。

不负责：交易执行、下单。本仓库不含生产交易能力。

允许依赖：``platform``、``contracts``、``domain``、``strategy``。

职责定义见 ``docs/architecture/layers/portfolio.md``。
"""

__all__: list[str] = []
