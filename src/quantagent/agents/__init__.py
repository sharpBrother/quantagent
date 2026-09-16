"""agents：研究 Agent 层。

负责：把下游计算结果组织成可解释的研究观点——宏观、债券择时、黄金择时、
风格轮动、行业轮动、风控、组合。每个 Agent 输出观点、依据与不确定性。

Agent 的观点是**研究展厅内容，不是生产仓位，也不自动授权交易执行**。这条
边界继承自旧仓，必须在发布契约中保持显式。

不负责：自己算因子或跑回测。Agent 消费 ``features`` / ``strategy`` /
``portfolio`` 的结果，不重复实现计算。

允许依赖：``platform``、``contracts``、``domain``、``features``、``models``、
``strategy``、``portfolio``。

职责定义见 ``docs/architecture/layers/agents.md``。
"""

__all__: list[str] = []
