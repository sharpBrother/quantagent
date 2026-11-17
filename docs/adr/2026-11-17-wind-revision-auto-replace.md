---
title: Wind 源镜像修订自动跟随
status: active
created: 2026-11-17
updated: 2026-11-17
applies_to:
  - src/quantagent/ingest/writers/wind_page.py
  - src/quantagent/cli/ingest.py
  - AGENTS.md
supersedes: null
superseded_by: null
---
# Wind 源镜像修订自动跟随
## 背景
Wind 增量按 `OPDATE+OBJECT_ID` 拉取。源端会对历史行重发 `OPMODE=1`。原规则是
指纹变了就拒绝覆盖，要人工传 `--replace-existing`。2026-11-16 的 `ASHAREEODPRICES`
有 4,884 行重发，覆盖 `603273.SH`、`601881.SH`、`688188.SH` 的整段历史，变化都在
复权列（主要是 `S_DQ_ADJCLOSE_BACKWARD`）。除权或复权因子更正会反复触发这种重发，
人工放开会让日更频繁停下。负责人裁定：不做人工处理，全自动。
## 决策
1. 已有键的指纹变了，逐列比较业务字段（除 Wind 系统列 `OPDATE`、`OPMODE`、
   `gsUTime`、`gsCTime`、`mopdate` 与主键外的全部源列）。
2. 业务字段全部相等：跳过不写，计入 `metadata_skipped`。库里系统列旧于源端。
3. 变化全部落在该数据集声明的 `AUTO_REPLACE_COLUMNS` 里：同一事务内 DELETE+INSERT，
   计入 `auto_replaced`，照常写后回读。`ASHAREEODPRICES` 声明七个复权列。
4. 其余变化，以及 `OPMODE=2`，仍然拒绝覆盖，需要 `--replace-existing`。大表任务的
   这个参数一次只放开一张表。
## 理由
- 源镜像只反映源端当前状态（[2026-09-17 ADR](2026-09-17-no-source-vintage-archive.md)），
  跟随源端修订不违背源面语义，被覆盖的旧值本来就不留。
- 自动替换范围写死在代码常量里，就是 AGENTS.md §6.4 要求的“指定范围”。不复权字段
  变了多半是源端异常，继续 fail-closed。
- 复权列被改写后，已写入 `feature.value` 的因子值不会自动重算，新旧输入可能不同。
  因子长表按身份键追加，旧值保留。
## 后果
- 其他数据集出现同类重发时，按证据把列加进 `AUTO_REPLACE_COLUMNS`，并在这里补一句。
- 用复权价重算历史因子时，结果可能与先前写入的值不同，对拍要先核对输入。
