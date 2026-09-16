---
title: 回测语义合同先行，内核按场景分设
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/strategy/backtest/
  - tests/golden/
supersedes: null
superseded_by: null
---

# 回测语义合同先行，内核按场景分设

## 背景

旧仓有多个回测实现，初版方案提出"收敛为唯一一套回测引擎"。

这个目标需要修正。先把对象列清楚：

| 对象 | 性质 |
|---|---|
| `strategy_engine/backtest.py` 的 `BacktestEngine` | 组合级再平衡仿真，含账户、成交、成本、调仓、checkpoint 恢复 |
| `strategy/generic_backtest_framework.py` 的 `GenericSelectionBacktest` | 旧选股回测框架，与上者场景重叠 |
| `alpha_factory/group_backtest.py` | 因子分组收益，**不是**组合仿真，无账户 |
| `strategy/ah_premium_hk_backtest.py`、`convbond_backtest.py`、`可转债套利.py` | 一次性专用脚本，部分是逐笔/套利语义 |
| `strategy/etf_quadrant_*_backtest.py`（4 个）、`etf_style_rotation_backtest.py`、`growth_stock_2_engine_backtest.py`、`did_stock_3_backtest.py` | 按策略各写一份的**入口脚本** |
| `enhanced_500_*_backtest.py`、`etf_sector_rotation` 内 `EtfStrategy` | 旁路实现 |

清点后的事实：真正在场景上重叠的执行内核只有 `BacktestEngine` 与
`GenericSelectionBacktest` 两套；`group_backtest` 本就属于另一类（无账户的
向量化计算）；其余十几个文件是**入口脚本而非引擎**。

入口脚本的重复来自"每个策略写一个 main"，这个问题由 CLI 与 Dagster asset
解决，不是回测引擎的问题。如果误把入口脚本数量当引擎数量，就会得出"要把
十几套引擎合成一套"的错误目标。

## 决策

### 先统一语义

一份「回测语义合同」，所有执行路径无条件遵守，落
`strategy/backtest/contract/` 并配可执行 schema。四部分：

1. **信号与执行时间**：`signal_dt` / `decision_dt` / `execution_dt` 三者
   分离；成交价口径与 T+N 结算规则显式声明
2. **收益、复权、现金与成本**：收益定义、复权口径与因子来源、现金账户与
   利息、成本模型的统一参数结构
3. **缺价、停牌与不可交易**：判定与处置；缺价不得静默用前值填充
4. **输入、结果与运行身份**：输入 = `universe_id` + `as_of` + 信号来源
   identity + 成本参数 hash；结果 = 统一 schema；身份 = `run_id` +
   `code_version` + `config_digest`

### 内核按场景分设

| 内核 | 场景 | 账户模拟 |
|---|---|---|
| `vectorized` | 因子分组收益、IC 序列 | 不需要 |
| `rebalance` | 多资产月频配置、风格轮动、ETF 轮动 | 需要，不到逐笔 |
| `event` | 套利、日内、订单级 | 需要订单与成交明细 |

三者输出同一套结果 schema，因此可以互相对照。

### 合并由行为对照决定

是否用一个内核替换另一个，判据是行为对照测试：同一组输入下，`nav`、
`turnover`、持仓序列在给定容差内一致。

**不以文件数减少作为验收标准。**

完整设计见 [../architecture/backtest-contract.md](../architecture/backtest-contract.md)。

## 理由

1. **统一语义的收益确定，合并内核的收益不确定**。语义不统一时，两次回测
   结果不同无法定位原因；语义统一后，即使有三个内核，结果也是可比的。
2. **三类场景的执行路径本就不同**。把因子分组收益塞进带账户的路径，需要
   虚构账户、虚构成交、虚构现金流，结果是慢、难解释，而且分组收益本来的
   语义被账户逻辑扭曲。
3. **合并语义不同的实现会得到带一堆开关的类**。文件数少了，理解成本更高。
4. **对照测试需要合同作为前提**。没有统一的结果 schema，"行为一致"这句话
   连比什么都说不清。所以合同必须先行。

## 被否方案

| 方案 | 否决理由 |
|---|---|
| 唯一一套引擎承载所有场景 | 三类场景执行语义不同，强行合并需要虚构不存在的概念 |
| 保留现状，各场景各自实现 | 语义不统一，结果不可比，这是当前的主要问题 |
| 先合并内核再统一语义 | 合并的正确性无法验证——没有合同就没有"一致"的定义 |
| 以文件数减少作为重构目标 | 会驱动出错误的合并 |
| 把 `group_backtest` 合进 `BacktestEngine` | 它本就是另一类（无账户），合并会扭曲其语义 |

## 代价

1. **三个内核意味着三份维护量**。通过共享 `contract/` 缓解，但执行逻辑确实
   是三份。
2. **合同定版需要前置投入**。在写任何内核之前要把四部分语义全部想清楚，
   而有些细节（如涨跌停的部分成交）只有实现时才会暴露。
3. **对照测试的工作量不小**。要构造覆盖停牌、涨跌停、缺价、成分调整、现金
   留存的输入集，并逐项归因差异。
4. **可能最终发现两套确实该合并**，前期的"分设"投入部分浪费。但反向的错误
   代价更大。

## 推论

1. **`contract/` 是唯一强制共享的部分**。内核可以不同，合同不能不同。
2. **结果 schema 包含 `diagnostics`**：不可交易样本数、缺价样本数、被处置
   的情形计数。这让"这次回测有多少样本被特殊处置"成为一等结果，而不是藏在
   日志里。
3. **结果 schema 包含 `pit_report`**。各输入的等级、`pit_from`、回测区间
   中落在不可信区间的样本占比。
4. **`event` 内核按需实现**。当前只有可转债套利一处可能需要，且该逻辑是否
   保留还未定。
5. **对照容差显式设定**（如 nav 相对误差 1e-8、换手率 1e-6），不用"看起来
   差不多"作为标准。
6. **落地顺序不可颠倒**：合同 → `rebalance` → `vectorized` → 与旧实现
   对照 → 判定 `GenericSelectionBacktest` 去留 → `event` 按需。
