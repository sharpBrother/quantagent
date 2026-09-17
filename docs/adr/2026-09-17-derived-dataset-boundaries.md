---
title: 因子配套派生数据集的层归属
status: active
created: 2026-09-17
updated: 2026-09-17
applies_to:
  - src/quantagent/lake/
  - src/quantagent/features/
  - src/quantagent/strategy/backtest/
  - docs/architecture/derived-datasets.md
supersedes: null
superseded_by: null
---

# 因子配套派生数据集的层归属

## 背景

P0 的设计文档只定义了两个派生数据集：因子值长表
（[feature-storage.md](../architecture/feature-storage.md)）与组合回测结果
合同（[backtest-contract.md](../architecture/backtest-contract.md)）。

旧仓 `alpha_factory` 实际有一族：`universe_member_d`、`forward_return_d`、
`factor_value_d`、`factor_snapshot_d`、`exposure_d`、`metric_d`、
`group_nav_d`、`factor_corr_d`、`alert_d`，以及按资产类别复制的 ETF 平行表
`etf_factor_metric_d` / `etf_factor_group_nav_d`。

缺口是真实的：股票池物化在哪、评价指标存哪、分组净值归哪一层、ETF 是否
另开表，四个问题在 P0 文档里都无法回答。留到实现阶段临时决定，就是旧仓
表结构失控的复现路径。

## 决策

### 一、`universe_member` 物化在 `mart`，区间表而非每日快照

规则留在 `domain/universe`，物化结果进 `mart`。

理由是依赖方向：`feature` 计算要读股票池，而数据分层禁止 `mart` 反向读
`feature`。放进 `feature` 层会让「因子读因子层的另一个数据集」成为常态，
分层约束随即失效。

区间表而非每日快照，因为成员关系的时间形态是 `interval`。旧表按
`(trade_date, universe_id, stock_code)` 逐日展开，全A 池十年约 1300 万行，
其中绝大多数相邻行完全相同。

同时**不复制资产维度**（`stock_name`、`industry_code`、`mv`、`is_st` 等）。
旧表复制了七个这样的字段，使同一口径有两处来源且无一致性保证。

### 二、`feature_metric` 与因子值同层、独立数据集、指标长表化

归 `feature` 层，但不进因子值长表——metric 没有 `asset_id` 维度，合表会让
该字段半数为空，且分区键与排序键无法同时服务两种访问模式。

指标拆成 `(metric_id, window)` 两个维度。旧 `metric_d` 把 14 个指标平铺成
列，其中 8 列只是同两个指标的四个窗口；加一个窗口要改表结构和全部下游。

**`knowledge_dt` 取因子与 `forward_return` 可见日的较晚者。** 这是本条决策
最实质的部分：`event_dt = T` 的 20 日 IC 要到 T+20 的收益可见后才能算出，
因此**不存在「今天的 IC」**。这条必须进发布层契约，否则会被「看板要显示
最新数据」这个需求悄悄破坏。

`health_score` / `health_state` 不进数据集——阈值判定结果不是观测值，固化
成历史行会让历史判定无法随阈值更新重算。

### 三、`group_nav` 归 `signal` 层，复用回测结果合同

因子分组净值是 `vectorized` 内核的输出，在统一 `nav` schema 上加
`(feature_key, group_no)` 两个维度。

理由：它经过了「权重到收益」的执行语义——调仓时点、收益口径、停牌与缺价
处置全部适用回测语义合同。放进 `feature` 层等于在因子层重复实现一遍这套
语义，而 [backtest-contract-first](2026-09-16-backtest-contract-first.md)
的整个论证前提是这套语义只能有一处定义。

多空组合占一个约定的 `group_no` 哨兵值，不像旧表那样把 `long_short_nav`
重复写在每个分组行上。

### 四、ETF 与股票共表

因子值、metric、universe、group_nav 全部共表，`asset_class` 作字段与候选
分区键。ETF 独有粒度的事实（折溢价、IOPV、份额、跟踪误差、申赎清单）另立
`mart` 事实表。

**区分标准是粒度，不是资产类别。**

旧仓的 ETF 平行表是「一因子一表」表爆炸的同构形态，只是分裂维度从因子换成
了资产类别。代价是查询、评价函数、发布链路各写两遍，且两遍会逐渐漂移。

### 五、`forward_return` 落 `mart`，防泄漏做进数据

前瞻收益是行情派生的口径事实，归 `mart`。三道防线：

1. `knowledge_dt` = 区间**结束日**的行情可见日，于是标准的
   `knowledge_dt <= as_of` 过滤天然挡掉未实现收益；
2. 契约标注 `usage: evaluation_only`，宽矩阵构建路径读到即报错退出；
3. `horizon` 与 `return_kind` 是维度而非固定列。

第一条是关键——**把防泄漏做进数据，而不是做进纪律**。依赖「记得不要用未来
收益做特征」的方案迟早会失效。

## 被否方案

| 方案 | 否决理由 |
|---|---|
| `universe_member` 放 `feature` 层 | 制造 `mart` → `feature` 反向依赖 |
| metric 合进因子值长表 | `asset_id` 半数为空，分区与排序键冲突 |
| metric 沿用宽表（每指标一列） | 新增指标或窗口要改 schema 与全部下游 |
| `group_nav` 归 `feature` 层 | 执行语义要重复实现，且无法与回测内核对照 |
| `group_nav` 在两层各存一份 | 两份口径必然漂移，且无机制检出 |
| ETF 另开平行表 | 表爆炸的同构形态，全链路双写并漂移 |
| `forward_return` 不持久化、评价时现算 | 现算路径无 `knowledge_dt`，防泄漏退回靠纪律 |

## 代价

**区间表的查询更麻烦。** 「T 日池内有哪些资产」从旧表的等值过滤变成区间
条件 `valid_from <= T AND (valid_to IS NULL OR valid_to > T)`。这个代价是
实际的，缓解手段是 `UniverseRepository` 端口提供 `members_at(as_of, dt)`
方法，让调用方永远不手写区间条件。如果后续发现截面查询是绝对主导的访问
模式，可以在 `_matrix/` 那样的纯缓存目录里物化逐日展开，但事实源仍是区间表。

**metric 长表化后单点查询要带更多过滤条件。** 旧表一行拿到 14 个指标，
现在要 14 行。看板类查询需要 pivot。换来的是新增指标不动 schema。

**ETF 共表意味着 ETF 的稀疏性会影响共享分区。** ETF 数量比股票少两个量级，
如果分区键里没有 `asset_class`，ETF 的因子值会稀疏散布在以股票为主的文件
里。这是把 `asset_class` 列为候选分区键的原因，最终以 P1 的 benchmark 定。

**「不存在当日 IC」会被当成缺陷反复提出。** 这是正确性要求而不是实现不足，
但它违反直觉，所以需要在发布层显式说明而不只是让数字为空。

## 推论

1. `publish` 层契约必须体现「不存在当日 IC」，且以可见的说明而非空值呈现。
2. `models/matrix/` 必须实现 `usage: evaluation_only` 的 fail-closed 拦截，
   这是 `forward_return` 第二道防线的落点。
3. `UniverseRepository` 端口必须提供按日取成员的方法，不把区间条件暴露给
   调用方。
4. `vectorized` 内核与 `rebalance` 内核的对照测试可以直接用 `group_nav`
   作为对照对象，因为两者共享 `nav` schema。
5. 旧仓 `factor_snapshot_d`、`exposure_d`、`factor_corr_d`、`alert_d` 的
   归属仍未裁定，列在
   [derived-datasets.md](../architecture/derived-datasets.md) 末尾，实现到
   相应阶段前必须先定，不允许实现时临时决定。
