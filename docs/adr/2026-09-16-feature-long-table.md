---
title: 因子统一为长表存储
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/features/
  - src/quantagent/models/matrix/
supersedes: null
superseded_by: null
---

# 因子统一为长表存储

## 背景

旧项目不是清一色「一因子一表」，而是**两套模式并存**：

- `factors/` 沿用 `stock_<factor>` 模式，运行时 `if not exists ... CREATE
  TABLE` 建表。后果是表数量爆炸、跨因子 JOIN 昂贵、需事后补覆盖索引
  （`docs/create_performance_factor_single_indexes.sql` 就是补救产物）、
  表结构没有单一定义处。
- `alpha_factory_factor_value_d` 已经是带 `visible_date` 的长表。

所以这不是"从零选格式"，而是"两套模式里选一套定为标准"。

## 决策

**长表是因子的唯一交换与保存格式。** `var/lake/feature/` 下的长表是事实源，
所有跨模块交换、持久化、发布都以它为准。

同时补齐 alpha_factory 长表缺的部分：版本与参数语义（见
[2026-09-16-feature-identity-triplet.md](2026-09-16-feature-identity-triplet.md)）。

训练用宽矩阵是**可重建的派生物化**，由 `matrix_id` 与输入版本强绑定，落
`var/lake/_matrix/`，是纯缓存。

## 理由

1. **表数量与因子数量解耦**。新增因子不新增表、不需要 DDL、不需要补索引。
2. **跨因子查询自然**。全因子截面是一次分区扫描加过滤，不是 200 路 JOIN。
3. **schema 稳定**。长表结构固定，因此契约稳定，物化逻辑统一。
4. **已有验证**。`alpha_factory_factor_value_d` 已经在旧仓跑通了这个模式，
   不是未经检验的设计。
5. **PIT 字段有统一归属**。`knowledge_dt` 与 `pit_grade` 是长表的固定列，
   不需要在每张因子表里各自定义。

## 被否方案

| 方案 | 否决理由 |
|---|---|
| 一因子一表 | 表爆炸、跨因子 JOIN 昂贵、需逐表补索引、结构无单一定义处。旧仓已验证其代价 |
| 宽表为事实源（列即因子） | 新增因子要改 schema；因子数量增长后列数失控；稀疏因子浪费空间 |
| 长表 + 宽表双事实源 | 两份事实源必然不一致，且不一致是静默的 |
| 每个研究线各自存储 | 跨线复用因子变成数据搬运，且口径无法统一 |

## 代价

1. **单因子长区间查询不如宽表直接**。需要按 `feature_key` 过滤，依赖排序键
   与 row group 统计。这是排序键冲突的来源之一，见 P1 benchmark。
2. **训练需要 pivot**。长表到宽矩阵的转换有成本，因此需要 `_matrix/` 缓存
   层，这是额外的复杂度。
3. **每行携带身份字段的存储开销**。`feature_id`、`definition_version`、
   `param_hash` 在每一行重复。通过字典编码压缩缓解，但仍有开销。
4. **类型统一为 float64**。长表的 `value` 列只能有一种类型，因此整型因子
   和布尔因子也存成浮点。

## 推论

1. **`_matrix/` 是纯缓存，不是事实源**。可整体删除重建，不入 git，不参与
   发布。任何从 `_matrix/` 直接取数做分析的行为都是错的——一旦有人这么做，
   缓存就不能随意删除了。
2. **宽矩阵与输入版本强绑定**。`matrix_id` 由 `feature_set_id`、
   `universe_id`、`date_range`、`as_of` 以及全部输入因子的
   `(definition_version, param_hash)` 计算。任一输入变化即换 id，旧缓存
   自然失效。这堵住了"参数改了但训练还在用旧矩阵"的静默错误。
3. **物理布局待实测**。分区键、文件大小、排序键、压缩参数以 P1 benchmark
   结论为准。明确的反面约束是 `feature_id` 不进分区键——全A 约 5500 只乘
   200 个因子会碎成 KB 级小文件。
4. **旧仓因子值不迁移**。因子属于"可以重算的派生数据"，在新链路重建，完成
   后与旧库交叉校验。
