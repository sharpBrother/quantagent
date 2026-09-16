---
title: PIT 由声明式规则定义，不由字段约定
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/contracts/visibility/
  - src/quantagent/domain/pit/
  - src/quantagent/features/
supersedes: null
superseded_by: null
---

# PIT 由声明式规则定义，不由字段约定

## 背景

初版设计提出"每张表加 `event_dt` 与 `knowledge_dt` 两列即实现 PIT"。这个
方案不成立，原因有三：

1. **两列无法表达三条独立的时间轴**。业务时间、来源发布时间、系统采集时间
   是三件不同的事，而且**三者都不是 PIT**。
2. **不同数据集的可见性规则完全不同**。交易所行情收盘后可见，财报以公告日
   为准，统计局 CPI 按官方发布日历，卖方一致预期按供应商更新节奏。这四条
   规则的形式没有共同点，不可能用一个字段约定覆盖。
3. **字段里的值无法审查**。`knowledge_dt` 是一个日期，看不出它是怎么算
   出来的、可信度多高、缺失时用了什么兜底。

旧仓的实现方式也印证了这一点：PIT 是读取时用
`ROW_NUMBER() OVER (...) WHERE visible_col <= as_of` 实现的，规则散在各处
SQL 里，无法枚举、无法审查、无法判断某个数据集到底用了哪条规则。

## 决策

**可见性规则是一等公民**：声明式的、可测试的、可被引用的 YAML，放
`src/quantagent/contracts/visibility/`，与代码一同版本化。

```yaml
dataset: mart.fin_statement
temporal_kind: period_with_revision
visibility:
  rule: source_field
  field: ann_dt
  grade: A
  rationale: 以公告日为准
  fallback:
    rule: statutory_deadline
    grade: B
```

内置规则类型：`same_day_close`、`source_field`、`release_calendar`、
`statutory_deadline`、`fixed_lag`、`ingest_time`。

`knowledge_dt` 是这些规则经 `domain/pit` 求解后的**派生结果**，不是任何
源字段的别名。

完整设计见 [../domain/pit-rules.md](../domain/pit-rules.md)。

## 理由

1. **规则可枚举**。`ls contracts/visibility/` 就是全部规则的清单。想知道
   "哪些数据集用了兜底规则"是一次 grep。
2. **规则可测试**。`domain/pit` 是纯规则层，规则求解的测试不需要数据库。
3. **规则可批量修改**。发现某类数据集的规则定错了，改 YAML 重算，不用改
   散落各处的 SQL。
4. **等级与理由强制携带**。每条规则必须有 `grade` 与 `rationale`，让
   "这个可见日多可信"成为可回答的问题。
5. **缺失可检测**。规则缺失是唯一 fail-closed 的情形，CI 校验每个数据集
   是否都有规则。

## 被否方案

| 方案 | 否决理由 |
|---|---|
| 两列约定（`event_dt` + `knowledge_dt`） | 无法表达三条时间轴，无法表达不同数据集的不同规则，无法审查 |
| 规则写在 Python 函数里 | 无法枚举、无法批量修改；且规则会和取数逻辑纠缠 |
| 规则存数据库表 | 规则应与代码一同版本化，存库会让"代码版本"和"规则版本"脱钩 |
| 读取时用 SQL 表达（旧仓做法） | 规则散落，无法枚举、审查或批量修改 |
| 由使用方自行决定 lag | 同一数据集在不同研究线用不同 lag，结果不可比 |

## 代价

1. **多一层间接**。想知道某个数据集的可见日怎么算，要去看 YAML 而不是直接
   看字段。
2. **规则引擎本身需要实现和维护**。六种内置规则类型，每种都要有测试。
3. **发布日历是额外的数据维护项**。`release_calendar` 规则依赖发布日历，
   它本身是一份要维护的数据。
4. **规则变更的影响面大**。改一条规则会改变所有历史 `knowledge_dt`，因此
   变更流程比普通代码变更重。

## 推论

1. **因子的 `knowledge_dt` 与 `pit_grade` 自动推导，不接受人工填写**。
   写入函数拒绝调用方传入这两个字段。`knowledge_dt` 默认取输入最大值加
   计算延迟，只允许更严格；`pit_grade` 沿依赖图取最差值，不可抬升。
2. **规则缺失 fail-closed，低等级不阻断**。这两条的区别很重要：规则缺失
   意味着"连什么时候能知道都没定义"，任何时间序列研究都不成立；低等级
   意味着"知道它不太可信"，那是可以在知情前提下使用的。
3. **低等级数据的管控是声明式的**。回测、信号、发布产物强制携带
   `pit_report`，发布层强制展示。是否采信由人判断，但信息不得隐藏。
4. **读取接口不提供无 `as_of` 的路径**。只要有这条路，它就会被用在需要
   PIT 的地方。
5. **规则变更必须重算受影响的因子**，不允许新旧规则的结果混存。
