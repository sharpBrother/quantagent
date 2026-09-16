---
title: strategy 层职责
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/strategy/
---

# strategy：信号生成与回测

## 负责

| 子模块 | 职责 |
|---|---|
| `signals/` | 从因子、模型预测或规则产出目标信号与目标权重 |
| `costs/` | 成本模型：佣金、印花税、过户费、冲击成本、滑点 |
| `backtest/contract/` | 回测语义合同的类型与校验 |
| `backtest/vectorized/` | 向量化截面研究内核，无账户 |
| `backtest/rebalance/` | 组合级再平衡仿真内核，有账户与成本 |
| `backtest/event/` | 事件驱动逐笔模拟内核 |

## 不负责

| 排除项 | 正确归属 |
|---|---|
| 因子计算、模型训练 | `features` / `models` |
| 组合优化、风险预算 | `portfolio` |
| 下单、交易执行 | 不在本仓库范围内 |

## 允许依赖

`platform`、`contracts`、`domain`、`features`、`models`。

## 设计要点：一份合同，多个内核

**统一的是语义，不是类。** 三类研究场景的执行路径本就不同，不预设合并：

| 内核 | 场景 | 账户模拟 |
|---|---|---|
| `vectorized` | 因子分组收益、IC 序列 | 不需要 |
| `rebalance` | 多资产月频配置、风格轮动、ETF 轮动 | 需要，不到逐笔 |
| `event` | 套利、日内、订单级 | 需要订单与成交明细 |

三者输出同一套结果 schema，因此可以互相对照。是否用一个内核替换另一个，
判据是**行为对照测试**（nav / turnover / 持仓序列在容差内一致），**不以
文件数减少作为验收标准**。

详见 [../backtest-contract.md](../backtest-contract.md)。

## 硬约束

- **信号与执行时间三者分离**：`signal_dt`（受 PIT 约束的信号生成日）、
  `decision_dt`、`execution_dt`。成交价口径与 T+N 结算规则显式声明。
- **缺价不得静默用前值填充**。缺失就是缺失。需要处置时按声明的规则处置，
  且处置方式进结果记录。
- **不填充、不跨日池化**。不补 0、不补前值、不跨日合并分母。
- **结果携带 `pit_report`**：各输入的 PIT 等级、`pit_from`、回测区间中落在
  不可信区间的样本占比。
- **身份完整**：`run_id` + 代码版本 + 配置 digest。身份变了就是新结果，不
  复用旧结论。

## 典型反例

- **一个引擎承载所有场景**。把因子分组收益塞进带账户的执行路径，会为了
  适配而引入无意义的虚拟账户和虚拟成交，结果既慢又难解释。旧仓
  `alpha_factory/group_backtest.py` 本来就是无账户的分组收益，它不应该被
  合并进 `BacktestEngine`。
- **以文件数减少作为重构成功标准**。合并前必须有行为对照证据；对照不通过
  说明语义本就不同，应当分别保留并写明差异来源。
- **选股类不继承统一接口、靠 adapter 包装**。旧仓 `strategy/GrowthStock_2`
  不继承 `BaseStrategy`，靠 `strategy_engine/adapters/` 包装，导致
  `enhanced_optimizer/risk_budget_engine.py` 同时 import 了原实现和适配器
  两条路径。新仓的策略直接实现统一接口。
- **函数内延迟 import 掩盖循环依赖**。旧仓 adapters 对 `strategy.*` 多为
  函数内 `from strategy.xxx import`，把环藏起来了。依赖该断就断，不靠延迟
  import 绕过。
- **成本参数散落在各策略里**。成本模型统一在 `costs/`，参数进配置并计入
  配置 digest，否则两次回测结果不同却无法定位原因。

## 对应的机械检查

- import-linter `只有 ingest 与 adapters 可以接触 PostgreSQL 驱动`。
- import-linter `业务层不得依赖 composition root`。
- `tests/contracts/`：三类内核的结果 schema 一致性。
- `tests/golden/`：与旧仓 `BacktestEngine` 的行为对拍。
