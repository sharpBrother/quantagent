---
title: agents 层职责
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/agents/
---

# agents：研究 Agent 与观点组织

## 负责

把下游计算结果组织成可解释的研究观点。每个 Agent 输出三样东西：观点、
依据、不确定性。

| 子模块 | 领域 |
|---|---|
| `base/` | Agent 基类与观点数据结构 |
| `macro/` | 信用周期、流动性、利率、宏观环境判断 |
| `bond/` | 利率债指数多空（相对现金） |
| `gold/` | 黄金价格指数多空（相对现金） |
| `style/` | 成长、价值、红利、小盘、大盘 |
| `sector/` | 行业强弱排序、行业景气度 |
| `risk/` | 波动率、风险水平、拥挤度 |
| `portfolio/` | 仓位管理、配置建议 |

## 不负责

| 排除项 | 正确归属 |
|---|---|
| 自己算因子 | `features` |
| 自己跑回测 | `strategy` |
| 自己做组合优化 | `portfolio` |
| 发布产物装配 | `publish` |

Agent 是**组织者与解释者**，不是计算者。如果某个 Agent 里出现了因子公式
或回测循环，说明计算该往下沉。

## 允许依赖

`platform`、`contracts`、`domain`、`features`、`models`、`strategy`、
`portfolio`。

## 硬约束

- **Agent 观点是研究展厅内容，不是生产仓位，不自动授权交易执行。** 这条
  边界继承自旧仓，必须在发布契约中保持显式声明。
- **观点必须可解释**。每个观点携带依据（哪些输入、什么阈值、什么规则）。
  无法解释的输出不发布。
- **观点必须带 PIT 等级**。Agent 的 `pit_grade` 同样沿依赖图取最差值继承。
- **观点必须带身份**：`run_id`、数据截止日、代码版本、配置 digest。

## 典型反例

- **Agent 里内嵌计算**。旧仓的风格轮动分域混乱——`agent_style_rotation/`
  生产行业评分表，`style_rotation/` 做成长价值与大小盘策略，两者名字相似
  但职责不同且互不 import。新仓里表生产属于 `features`，策略属于
  `strategy`，Agent 只负责把结果组织成观点。
- **把 Agent 状态展示当作 Agent 有决策权**。可视化能力不等于生产决策能力。
- **原型长期停留在原型状态**。旧仓 `agent_risk_monitor/` 只有测试引用它，
  `agent_common/` 是薄守卫。Agent 要么接入主链路，要么明确标注为未接入并
  设定期限。

## 对应的机械检查

- import-linter `只有 ingest 与 adapters 可以接触 PostgreSQL 驱动`。
- import-linter `业务层不得依赖 composition root`。
- `tests/contracts/`：观点数据结构必须包含依据、PIT 等级与身份字段。
