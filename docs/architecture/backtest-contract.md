---
title: 回测语义合同与分场景内核
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/strategy/backtest/
  - src/quantagent/strategy/costs/
  - tests/golden/
---

# 回测语义合同与分场景内核

## 立场

「唯一一套回测引擎」可能减少重复，也可能让一个类承载所有研究场景。因子分组
收益、月频资产配置和逐笔订单模拟不一定都适合同一条执行路径。

因此顺序是：**先统一语义，再由行为对照决定内核是否合并。**

## 一、先把旧仓的实现列清楚

「四套」这个说法需要落到具体对象。它们不是同一类东西，不能一句「重复」
带过：

| 对象 | 性质 | 处置倾向 |
|---|---|---|
| [`strategy_engine/backtest.py`](/Users/le/PycharmProjects/pycharm_workspace/strategy_engine/backtest.py) 的 `BacktestEngine` | 组合级再平衡仿真，含账户、成交、成本、调仓、checkpoint 恢复 | 作为 `rebalance` 内核的继承者 |
| [`strategy/generic_backtest_framework.py`](/Users/le/PycharmProjects/pycharm_workspace/strategy/generic_backtest_framework.py) 的 `GenericSelectionBacktest` 及象限/成长股派生 | 旧选股回测框架，与上者场景重叠 | 行为对照后决定合并或废弃 |
| [`alpha_factory/group_backtest.py`](/Users/le/PycharmProjects/pycharm_workspace/alpha_factory/group_backtest.py) | 因子分组收益，**不是**组合仿真，无账户 | 归入 `vectorized` 内核，不应塞进账户路径 |
| `strategy/ah_premium_hk_backtest.py`、`strategy/convbond_backtest.py`、`strategy/可转债套利.py` | 一次性专用脚本，部分是逐笔/套利语义 | 逐个定性，多数丢弃；套利逻辑若保留则归 `event` |
| `strategy/etf_quadrant_*_backtest.py`（4 个）、`strategy/etf_style_rotation_backtest.py`、`strategy/growth_stock_2_engine_backtest.py`、`strategy/did_stock_3_backtest.py` | 按策略各写一份的入口脚本 | 收敛为 `rebalance` 内核 + 策略配置 |
| `strategy/enhanced_500_joint_optimizer_backtest.py`、`strategy/enhanced_500_risk_budget_engine_backtest.py`、`etf_sector_rotation` 内 `EtfStrategy` | 旁路实现 | 收敛到 `rebalance` 内核 |

清点结论：真正的执行内核只有 `BacktestEngine` 与
`GenericSelectionBacktest` 两套在场景上重叠，`group_backtest` 本就属于
另一类，其余十几个文件是**入口脚本而非引擎**——它们的重复来自"每个策略
写一个 main"，这个问题由 CLI 与 Dagster asset 解决，不是回测引擎的问题。

这一点很重要：如果误把入口脚本数量当作引擎数量，就会得出"要把十几套引擎
合成一套"的错误目标。

## 二、必须统一的是语义

一份回测语义合同，所有执行路径无条件遵守。落
`src/quantagent/strategy/backtest/contract/`，配可执行 schema。

### 2.1 信号与执行时间

三个日期必须分离，不允许隐含：

| 字段 | 含义 |
|---|---|
| `signal_dt` | 信号生成日。受 PIT 约束——只能用 `knowledge_dt <= signal_dt` 的输入 |
| `decision_dt` | 决策日。通常等于或晚于 `signal_dt` |
| `execution_dt` | 执行日。通常晚于 `decision_dt` |

此外必须显式声明：

- **成交价口径**：开盘价、收盘价、VWAP、区间均价，四选一，不允许默认
- **T+N 结算规则**：A股 T+1 卖出限制、资金 T+0/T+1 可用
- **调仓触发方式**：固定频率、阈值触发、信号变化触发

隐含时间关系是回测最常见的错误来源，而且错了不报错。把三个日期拆开，就让
"信号用了当天收盘价，执行也用当天收盘价"这种问题在类型层面可见。

### 2.2 收益、复权、现金与成本

| 项 | 必须声明 |
|---|---|
| 收益定义 | 简单收益还是对数收益；含不含现金；是否年化 |
| 复权口径 | 前复权、后复权、不复权；复权因子来源与生效时点 |
| 现金账户 | 初始资金、利息率、是否允许透支 |
| 成本模型 | 佣金率与最低佣金、印花税、过户费、冲击成本模型、滑点 |

成本参数用统一的参数结构，参数集计入 `config_digest`。否则两次回测结果
不同却无法定位原因。

成本模型统一在 `strategy/costs/`，不允许各策略自带一份。

### 2.3 缺价、停牌与不可交易

判定与处置都要声明：

| 情形 | 需声明的处置 |
|---|---|
| 停牌 | 权重如何滚动、是否强制留仓、是否计入分母 |
| 涨跌停 | 是否可成交、部分成交如何处理 |
| ST / 退市 | 是否强制清仓、清仓价格口径 |
| 新股未开板 | 是否可买入 |
| 流动性下限 | 成交量占比上限、不满足时的处置 |
| 缺价 | 能否估值、估值用什么价 |

**硬约束：缺价不得静默用前值填充。** 这条来自研究正确性铁律。缺失就是
缺失；需要处置时按声明的规则处置，且处置方式与影响样本数进结果记录。

前值填充的危害是它让回测曲线变得"好看且连续"，掩盖了数据问题。

### 2.4 输入、结果与运行身份

**输入** = `universe_id` + `as_of` + 信号来源 identity + 成本参数 hash +
时间规则配置。

**结果** = 统一 schema，三类内核共享：

| 表 | 内容 |
|---|---|
| `nav` | 日期、净值、收益、现金比例 |
| `positions` | 日期、资产、权重、市值、数量 |
| `trades` | 日期、资产、方向、数量、价格、成本明细 |
| `turnover` | 日期、双边换手率 |
| `exposure` | 日期、因子或行业暴露 |
| `pit_report` | 各输入的 `grade`、`pit_from`、不可信区间样本占比 |
| `diagnostics` | 不可交易样本数、缺价样本数、被处置的情形计数 |

**运行身份** = `run_id` + `code_version` + `config_digest`。

`diagnostics` 是刻意加的：它让"这次回测有多少样本被特殊处置"成为一等
结果，而不是藏在日志里。

## 三、内核按场景分设，共享结果合同

三类研究场景的执行路径本就不同，不预设合并：

| 内核 | 典型用途 | 执行语义 | 账户模拟 |
|---|---|---|---|
| `vectorized` | 因子分组收益、IC 序列 | 权重到收益的矩阵运算 | 不需要 |
| `rebalance` | 多资产月频配置、风格轮动、ETF 轮动 | 按再平衡日调仓，账户加成本 | 需要，但不到逐笔 |
| `event` | 套利、日内、订单级 | 逐订单撮合 | 需要订单与成交明细 |

对应 `strategy/backtest/` 下：

```
backtest/
├── contract/      语义合同的类型与校验（唯一强制共享的部分）
├── vectorized/
├── rebalance/
└── event/
```

`event` 内核按真实需求决定是否在本轮实现。当前旧仓只有可转债套利这一处
可能需要它，且该逻辑本身是否保留还未定。

三者输出同一套结果 schema，因此**可以互相对照**——这是后面合并判定的
前提条件。

### 为什么不强行合并

把因子分组收益塞进带账户的执行路径，需要为它虚构账户、虚构成交、虚构现金
流。结果是慢、难解释，而且分组收益本来的语义（等权分组的截面收益）被账户
逻辑扭曲。

反过来，把账户仿真简化成矩阵运算会丢掉成交约束和现金约束，那不是同一个
问题的解。

## 四、合并的验收标准

是否用一个内核替换另一个，判据是**行为对照测试**：

同一组输入下，两者的 `nav`、`turnover`、持仓序列在给定容差内一致。

**不以文件数减少作为验收标准。**

对照不通过就说明两者语义本就不同，应当分别保留，并在文档中写明差异来源。
把语义不同的两套东西合并，只会得到一个带一堆分支开关的类——文件数少了，
理解成本更高了。

### 对拍的具体做法

放 `tests/golden/backtest/`：

1. 构造一组覆盖边界的输入：含停牌日、含涨跌停、含缺价、含成分调整、含
   现金留存。
2. 旧实现（`BacktestEngine`、`GenericSelectionBacktest`）在该输入上的输出
   作为基线。
3. 新内核跑同一输入，逐项比对。
4. 差异逐项归因：是新实现的 bug、旧实现的 bug、还是语义差异。前两者修代
   码，第三者写入文档并保留两套实现。

容差要显式设定（例如 nav 相对误差 1e-8，换手率 1e-6），不用"看起来差不多"
作为标准。

## 五、落地顺序

P4 阶段，顺序不可颠倒：

1. 定版语义合同与结果 schema
2. `rebalance` 内核落地（继承 `BacktestEngine` 的语义），输出统一 schema
3. `vectorized` 内核落地（继承 `group_backtest` 的语义）
4. 与旧实现行为对照，逐项归因
5. 判定 `GenericSelectionBacktest` 是合并还是废弃
6. `event` 内核按需

先出合同再出内核，是因为合同定义了什么叫"行为一致"。没有合同，对照测试
连比什么都说不清。
