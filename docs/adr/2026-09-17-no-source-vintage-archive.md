---
title: 源数据不做批次 vintage 归档
status: active
created: 2026-09-17
updated: 2026-09-17
applies_to:
  - src/quantagent/ingest/
  - src/quantagent/platform/storage/paths.py
  - db/migrations/src/
  - src/quantagent/contracts/visibility/
supersedes: adr/2026-09-16-no-source-vintage-in-pg.md
superseded_by: null
---

# 源数据不做批次 vintage 归档

## 背景

[源镜像层不做版本留存](2026-09-16-no-source-vintage-in-pg.md) 定了两件事：
PG `src_*` 只反映源端当前状态；再用
`var/lake/_vintage/<source>/<dataset>/batch_dt=.../` 把每次拉取的原样结果
append-only 存下来，作为 CDC 的廉价替代，并写进 P1 验收。

负责人裁定：源端静默改历史是小概率事件，由此引入的研究误差可以接受；源
表体量大，按批次落原样快照没有必要。

## 决策

1. **PG 源镜像仍然只反映当前状态**，不做 CDC、不做 SCD Type 2、不在库内
   留源端修订历史。这一条从被取代的 ADR 继承，没有改。
2. **采集批次的原始拉取结果不归档。** 不建 `var/lake/_vintage/`，ingest
   不写第二份源镜像。
3. **诚实标记保留。** 版本不可得的数据集继续在契约里写
   `pit_recoverable: false` 与 `pit_from`。不得用采集批次号伪造版本序列。
4. **`_ingested_at` 仍然不是 PIT 依据。** 没有 vintage 之后更不能拿采集
   时间冒充发布时间。

## 理由

1. **体积与收益不匹配。** 第一批就要镜像几十张源表。按日把原始拉取落盘，
   等于在 Parquet 上再养一套源库，而它回答的问题（源端是否悄悄改过旧值）
   在本项目的研究里极少成为结论的关键。
2. **静默修订是小概率。** 负责人明确接受：Wind / Tushare 改三年前一个数
   而我们无法证明改前是什么，由此带来的回测误差可以忍受。
3. **派生数据可重算，不靠源 vintage。** 因子、mart、信号本来就在 lake 里
   按契约重算；要回溯的是口径和代码，不是源端报文。
4. **没有归档就不要假装能升 PIT 等级。** 旧方案指望用观测序列把 C 抬到
   B。不做 vintage，这条路关闭，避免「目录在、数据没有、等级却写着 B」。

## 被否方案

| 方案 | 否决理由 |
|---|---|
| 维持原 ADR，P1 必须启动 `_vintage/` | 与存储预算和负责人裁定冲突 |
| 只归档「核心表」 | 核心表边界会漂，最后几乎全归档；和「数据量太大」同一问题 |
| 抽样或压缩后当 vintage | 不能再回答「当时源端给了什么」，归档失去唯一理由 |
| 回头做 PG CDC / SCD2 | 否决理由未变：源端多数不提供历史版本，复杂度与收益不匹配 |
| 用 `_ingested_at` 或批次号冒充版本 | 伪造市场可见时点，PIT 静默失效 |

## 代价

1. **源端静默修订不可回溯。** 这是刻意接受的误差，不是疏漏。
2. **无法回答「某日系统到底拉到了什么」。** 排障只能看当时的 PG 当前镜像
   与 run log，看不到原始报文。
3. **不能再靠观测序列把无发布时间的数据集从 C 抬到 B。** 没有源端
   `published_at` 或官方日历的，停在 C/D。
4. **「财报修订如何影响定价」这类题目做不了。** 旧方案也要等归档积累，
   现在则明确不做。

## 推论

1. **源层时间字段不得作 PIT 依据。** `domain/pit` 仍不接受 `_ingested_at`
   作为 `source_field`；`ingest_time` 规则仅用于上线后持续采集，且最高
   C，存量迁入必须 `pit_recoverable: false`。
2. **`VarPaths` 不提供 vintage 目录。** 业务代码不得自己拼 `_vintage/`。
3. **ingest 的落盘面只有 PG `src_*`（写闸约束）和 `src_<source>._batch`
   批次登记。** 原始拉取在内存里校验、写入、丢弃。
4. **某数据集将来确需版本语义**，走「新增旁表 + 契约声明」，不恢复全局
   vintage 目录。
5. **P1 验收不再包含 `_vintage/` 首批快照。**
