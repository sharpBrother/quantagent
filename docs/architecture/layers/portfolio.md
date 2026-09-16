---
title: portfolio 层职责
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/portfolio/
---

# portfolio：组合构建、风险与归因

## 负责

| 子模块 | 职责 |
|---|---|
| `construct/` | 权重构建与约束优化：风险平价、风险预算、均值方差、上下限与换手约束 |
| `risk/` | 风险度量：波动、因子暴露、集中度、拥挤度、回撤 |
| `attribution/` | 业绩归因：收益拆解到因子、行业、择时 |

## 不负责

| 排除项 | 正确归属 |
|---|---|
| 信号生成 | `strategy` |
| 回测执行 | `strategy.backtest` |
| 交易执行、下单 | 不在本仓库范围内 |
| 组合观点的表述与解释 | `agents` |

## 允许依赖

`platform`、`contracts`、`domain`、`strategy`。

## 依赖是分支，不是串行

组合风险允许**直读** `mart` 的行情与基础信息，加上自身持仓即可计算，不要求
先经过 `features` 或 `strategy`。这是四类合法分支之一，见
[../data-layers.md](../data-layers.md)。

跨层直读须在 Dagster 资产定义里声明 `reads:`，让血缘图可见。

`portfolio` 读自身持仓是时间维度上的前向依赖（T 日读 T-1 持仓），不构成
同层环。

## 典型反例

- **强制让风险计算穿过因子层**。为了"分层整齐"而把行情包一层因子再给风险
  模块，制造纯转发的中间资产，是冗余。
- **在组合层重新实现风险模型的口径**。因子暴露的定义只能有一处（`domain`
  的分类口径 + `features` 的暴露因子），组合层不得另起一套。
- **三套并行的优化实现**。旧仓 `enhanced_optimizer/`、`portfolio_engine/`、
  `multi_asset/` 三者职责重叠，且 `portfolio_engine/` 的生产消费者几乎只有
  `agent_risk_monitor/export.py`。优化算法收敛到 `construct/`，多资产与
  单资产的差别体现在配置而非独立模块。
- **把组合结果当作交易授权**。组合层的输出是研究与配置观点，不自动授权
  交易执行或生产调仓。这条边界继承自旧仓，必须在发布契约中保持显式。

## 对应的机械检查

- import-linter `只有 ingest 与 adapters 可以接触 PostgreSQL 驱动`。
- import-linter `业务层不得依赖 composition root`。
