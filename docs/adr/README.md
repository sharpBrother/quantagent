---
title: 决策记录索引
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - docs/adr/
---

# 决策记录（ADR）

## 规则

- 文件名：`YYYY-MM-DD-slug.md`，不使用编号
- **只增不改**。正文一经提交不改写
- 被新决策取代时：新文档写 `supersedes`，旧文档改 `status: superseded` 并写
  `superseded_by`，**正文保持原样**
- 与 `architecture/` 的分工：ADR 记录「当初为什么这么选」，活文档描述
  「现在是什么样」。前者不改写，后者持续改写

## 固定结构

1. **背景** — 当时面临的情况与约束
2. **决策** — 选了什么
3. **理由** — 为什么
4. **被否方案** — 考虑过但没选的，以及为什么没选
5. **代价** — 这个选择放弃了什么、以后可能后悔在哪
6. **推论** — 由这个决策直接导出的其他约束

第四和第五部分是 ADR 的核心价值。只写"选了什么、为什么好"的记录无法防止
后来的人重新提出已被否掉的方案。

## P0 初始决策

| 日期 | 决策 |
|---|---|
| 2026-09-16 | [存储选型：PostgreSQL + Parquet + DuckDB](2026-09-16-storage-selection.md) |
| 2026-09-16 | [PostgreSQL 分为研究数据面与控制状态面](2026-09-16-pg-two-planes.md) |
| 2026-09-16 | [源镜像层不做版本留存](2026-09-16-no-source-vintage-in-pg.md) |
| 2026-09-16 | [PIT 由声明式规则定义，不由字段约定](2026-09-16-rule-based-pit.md) |
| 2026-09-16 | [因子统一为长表存储](2026-09-16-feature-long-table.md) |
| 2026-09-16 | [因子身份拆分为三段](2026-09-16-feature-identity-triplet.md) |
| 2026-09-16 | [不可重算历史制品的冻结策略](2026-09-16-frozen-artifacts.md) |
| 2026-09-16 | [回测语义合同先行，内核按场景分设](2026-09-16-backtest-contract-first.md) |
| 2026-09-16 | [选择 Dagster 作资产化编排](2026-09-16-dagster-orchestration.md) |
| 2026-09-16 | [Python 3.12 作为唯一基线](2026-09-16-python-312-baseline.md) |
| 2026-09-16 | [文档体系去编号化](2026-09-16-docs-without-numbering.md) |
