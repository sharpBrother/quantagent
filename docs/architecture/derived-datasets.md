---
title: 派生数据集清单与归属
status: active
created: 2026-09-17
updated: 2026-09-18
applies_to:
  - src/quantagent/lake/
  - src/quantagent/features/
  - src/quantagent/strategy/backtest/
  - src/quantagent/contracts/schemas/lake/
  - src/quantagent/contracts/visibility/
supersedes: null
superseded_by: null
---

# 派生数据集清单与归属

## 为什么需要这一份

[feature-storage.md](feature-storage.md) 只定义了**因子值**长表，
[backtest-contract.md](backtest-contract.md) 只定义了**组合回测**结果合同。
但旧仓 `alpha_factory` 那一族远不止这两张表——`universe_member_d`、
`forward_return_d`、`metric_d`、`group_nav_d`、`exposure_d`、
`factor_snapshot_d` 都是现役数据集。只设计其中两个，剩下的会在实现阶段被
临时决定，那正是旧仓表结构失控的起点。

这份文档列全派生数据集，每个说清三件事：**归属哪一层、键是什么、
`knowledge_dt` 怎么来**。

## 清单

| 数据集 | 层 | 目录 | 粒度 |
|---|---|---|---|
| `universe_member` | `mart` | `var/lake/mart/universe_member/` | 股票池 × 资产 × 生效区间 |
| `forward_return` | `mart` | `var/lake/mart/forward_return/` | 资产 × 起始日 × horizon |
| `feature_value` | `feature` | `var/lake/feature/value/` | 资产 × 截面日 × `feature_key` |
| `feature_metric` | `feature` | `var/lake/feature/metric/` | `feature_key` × 股票池 × horizon × 指标 × 日 |
| `group_nav` | `signal` | `var/lake/signal/group_nav/` | `feature_key` × 股票池 × horizon × 分组 × 日 |

回测的 `nav` / `positions` / `trades` / `turnover` / `exposure` /
`diagnostics` 见 [backtest-contract.md](backtest-contract.md)，不在这里重复。

## universe_member：规则在 domain，物化在 mart

**归属 `mart` 而不是 `feature`。** 因为 `feature` 计算要读它，而 `mart`
不允许反向读 `feature`。放错一层会直接违反数据分层的不得反向依赖约束。

| 字段 | 类型 | 含义 |
|---|---|---|
| `universe_id` | string | 股票池身份，`digest(规则配置规范化 JSON)` |
| `asset_id` | string | 资产身份 |
| `valid_from` | date | 进入池的生效日 |
| `valid_to` | date | 退出池的生效日，仍在池内为 `NULL` |
| `member_weight` | float64 | 池内权重，等权池为 `NULL` 而不是 `1/N` |
| `knowledge_dt` | date | 该成员关系的可见日 |
| `pit_grade` | enum(A/B/C/D) | 继承自输入 |

### 三处与旧仓的刻意不同

1. **区间表，不是每日快照。** 旧 `alpha_factory_universe_member_d` 键是
   `(trade_date, universe_id, stock_code)`，全A 池十年约 1300 万行，其中
   绝大多数行在相邻日之间完全相同。区间表把它压到成员变动的次数量级。
   区间语义本身是 `temporal_kind: interval` 的要求，见
   [../domain/temporal-semantics.md](../domain/temporal-semantics.md)。
2. **不复制资产维度。** 旧表混进了 `stock_name`、`industry_code`、`mv`、
   `free_float_mv`、`is_st`、`is_suspended`、`list_days`。这些都是 `mart`
   基础信息表已有的事实，复制进成员表意味着同一个口径有两处来源，且没有
   任何机制保证它们一致。需要这些字段就 JOIN。
3. **分层池用多个 `universe_id` 表达。** 旧仓 `layered_universe` 另立一套
   概念；这里不加分层字段，每一层就是一个独立的 `universe_id`，规则配置
   里声明它从哪个父池派生。ETF 因子研究池沿用同一张表：旧
   `strategy_etf_list` / `strategy_etf_list_*` 的 `universe_id` 统一
   `universe_etf_*`（如 `universe_etf`、`universe_etf_2`、`universe_etf_rebate`），
   禁止按名单再建物理表。这些名册暂时不设 PIT（与 `ASHAREDESCRIPTION` 同类），
   不得当作 as_of 历史成分来读。

### 可见性

指数 / 行业成分**延续旧仓**：`as_of` 落在
`S_CON_INDATE <= as_of` 且 `(S_CON_OUTDATE IS NULL OR S_CON_OUTDATE >= as_of)`
即为当时成员。源表没有独立公告日，写入 `mart.universe_member` 时
`knowledge_dt = valid_from = S_CON_INDATE`。这与「公告日早于生效日」的通用
区间模型不矛盾：有公告日的源仍可把 `knowledge_dt` 填得更早；Wind 成分现在
没有这个字段。规则过滤池的 `knowledge_dt` 仍由输入推导。

## forward_return：落 mart，但必须防泄漏

前瞻收益是行情派生的口径事实，不是因子，所以归 `mart`。但它天然含未来
信息，是本项目最直接的一条前视泄漏通道。

| 字段 | 类型 | 含义 |
|---|---|---|
| `asset_id` | string | 资产身份 |
| `event_dt` | date | 区间起始日 |
| `horizon` | string | 前瞻窗口，如 `1d` / `5d` / `20d` / `60d` |
| `return_kind` | enum | `total` / `excess` |
| `benchmark_id` | string | `excess` 时的基准，`total` 时为 `NULL` |
| `value` | float64 | 区间收益 |
| `end_dt` | date | 区间结束日，由交易日历推出 |
| `knowledge_dt` | date | **= `end_dt` 的行情可见日**，不是 `event_dt` |
| `pit_grade` | enum(A/B/C/D) | 继承自行情 |

### 三道防线

1. **`knowledge_dt` 是 `end_dt` 的可见日。** 于是标准的
   `knowledge_dt <= as_of` 过滤天然挡掉未实现的收益，不需要额外规则。这是
   把防泄漏做进数据而不是做进纪律。
2. **契约标注 `usage: evaluation_only`。** `models/matrix/` 的宽矩阵构建
   路径读到这个标注直接报错退出，不允许 `forward_return` 进入特征集。
   `fail-closed`，不是警告。
3. **`horizon` 是行，不是列。** 旧 `alpha_factory_return_label_d` 用
   `ret_1d` / `ret_5d` / `ret_20d` / `ret_60d` / `excess_ret_*` 八列固定
   窗口，加一个窗口就要改表。长表化后 `horizon` 与 `return_kind` 都是维度。

## feature_metric：与因子值同层，但独立数据集

因子评价指标（IC、ICIR、覆盖率、多空收益、单调性、换手、rank 自相关）是
因子的评价结果，归 `feature` 层。

**但它不进因子值长表。** 因为粒度不同：metric 没有 `asset_id` 维度。混进
同一张表会让 `asset_id` 一半是空值，并让分区键与排序键无法同时服务两种
访问模式。

| 字段 | 类型 | 含义 |
|---|---|---|
| `event_dt` | date | 指标计算的截面日 |
| `feature_id` / `definition_version` / `param_hash` | string | 因子三段身份 |
| `universe_id` | string | 评价所用股票池 |
| `horizon` | string | 前瞻窗口 |
| `metric_id` | string | 指标身份，如 `rank_ic` / `icir` / `coverage` |
| `window` | string | 指标自身的统计窗口，截面指标为 `1d` |
| `benchmark_id` | string | 涉及超额时的基准，否则 `NULL` |
| `value` | float64 | 指标值 |
| `knowledge_dt` | date | **见下，不等于因子的 `knowledge_dt`** |
| `pit_grade` | enum(A/B/C/D) | 取因子与 `forward_return` 的更差值 |
| `computed_at` / `run_id` | timestamp / string | 运行身份 |

### 指标是行，不是列

旧 `alpha_factory_metric_d` 把 `ic`、`rank_ic`、`ic_mean_20d`、`icir_20d`、
`ic_mean_60d`、`icir_60d`、`ic_mean_120d`、`icir_120d`、`ic_mean_252d`、
`icir_252d`、`top_bottom_return`、`monotonicity_score`、`turnover`、
`rank_autocorr` 平铺成 14 列，其中 8 列是同两个指标的 4 个窗口。加一个
窗口或一个指标就要改表结构和全部下游查询。

拆成 `(metric_id, window)` 两个维度之后，`ic_mean_20d` 就是
`metric_id='ic_mean', window='20d'`，新增窗口不动 schema。

### knowledge_dt 是这里最容易错的一处

IC 衡量的是**因子值与后续收益的关系**，所以 `event_dt = T`、
`horizon = 20d` 的那一行，要到 T+20 个交易日的收益可见之后才能算出来。

```
feature_metric.knowledge_dt = max(
    因子的 knowledge_dt,
    forward_return(event_dt=T, horizon=h).knowledge_dt,   # 即 end_dt 的可见日
)
```

**推论：因子评价看板不存在「今天的 IC」。** 任何在 `as_of = T` 展示
`event_dt = T` 的 20 日 IC 的界面都是前视。这条必须在 `publish` 层的契约
里体现，因为它是最容易被「看板要显示最新数据」这个需求悄悄破坏的地方。

`health_score` / `health_state`（旧表的因子健康度）是阈值判定的结果，不是
观测值，归 `publish` 层的展示逻辑，不进 metric 数据集。阈值会随时调整，
把它固化成历史数据行会让历史判定无法随阈值更新而重算。

## group_nav：归 signal 层，复用回测结果合同

因子分组净值是 `vectorized` 内核的输出，走
[backtest-contract.md](backtest-contract.md) 的统一结果合同，在 `nav` 表的
基础上加两个维度。

| 字段 | 类型 | 含义 |
|---|---|---|
| `event_dt` | date | 净值日 |
| `feature_id` / `definition_version` / `param_hash` | string | 分组所用因子身份 |
| `universe_id` | string | 股票池 |
| `horizon` | string | 调仓周期 |
| `group_no` | int | 分组编号；多空组合为 `-1`（身份哨兵，不是把缺失组填成 0） |
| `group_return` | float64 | 当期分组收益 |
| `group_nav` | float64 | 分组累计净值 |
| `knowledge_dt` | date | 取因子与所用收益可见日的较晚者，**不是** `event_dt` |
| `pit_grade` | enum(A/B/C/D) | 输入木桶最差 |
| `pit_report` | JSON 文本 | 输入的 PIT 等级与不可信区间占比；契约暂无 struct 类型 |
| `run_id` / `code_version` / `config_digest` | string | 运行身份；`run_id` 计入键 |

**为什么归 signal 而不是 feature。** 它经过了「权重到收益」的执行语义
——调仓时点、收益口径、停牌处置、缺价处置全部适用回测语义合同。把它放在
`feature` 层意味着这套语义要在因子层重复实现一遍，而
[backtest-contract.md](backtest-contract.md) 的整个论证前提就是这套语义
只能有一处定义。

旧表把 `long_short_nav` 作为独立列重复写在每个 `group_no` 的行上（十分组
就重复十份同一个值）。改为多空组合占 `group_no = -1`，它和其他分组共享
schema，也就能走同一套对照测试。

分组净值也依赖前瞻窗口，因此带 `knowledge_dt`：过滤规则与 `feature_metric`
相同。没有这一列，`as_of` 过滤会退回到 `event_dt`，把未实现收益当成当日
可见。

## ETF 不另开表

**因子值、metric、universe、group_nav 全部与股票共表。** `asset_class` 是
字段；因子值表把它用作 hive 分区前缀，见
[../adr/2026-09-17-feature-value-parquet-layout.md](../adr/2026-09-17-feature-value-parquet-layout.md)。

旧仓 `alpha_factory_etf_factor_metric_d`、
`alpha_factory_etf_factor_group_nav_d`、`alpha_factory_etf_refresh_publish`
是按资产类别复制的一套平行表。这本质上是「一因子一表」表爆炸的另一种
形态——差别只是分裂维度从因子换成了资产类别。代价是每个查询、每个评价
函数、每条发布链路都要写两遍，并且两遍会逐渐漂移。

ETF 特有的事实（折溢价、IOPV、份额、跟踪误差、申赎清单）落 `mart` 的 ETF
专属事实表。**区分标准是粒度而不是资产类别**：粒度与股票一致的（因子值是
资产 × 日 × 因子）共表；ETF 独有粒度的另立事实表。

## 尚未设计的邻接数据集

旧仓这几个还没有归属裁定，实现到相应阶段前必须先定，不允许在实现时临时
决定：

| 旧表 | 内容 | 待定问题 |
|---|---|---|
| `alpha_factory_factor_snapshot_d` | 因子预处理中间态：去极值、中性化、标准化、打分、分位 | 是否持久化，还是作为纯内存中间态由 `param_hash` 保证可复现 |
| `alpha_factory_exposure_d` | 风格暴露的 `raw_value` / `processed_value` | 与因子值长表高度重叠，是否就是因子值的一个 `feature_id` 命名域 |
| `alpha_factory_factor_corr_d` | 因子两两相关性 | pairwise 粒度装不进 metric 的键，是否持久化还是查询时现算 |
| `alpha_factory_alert_d` | 因子健康度告警 | 归 `ops_*` 控制状态面（倾向），不是研究数据 |
