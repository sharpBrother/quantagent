---
title: Wind 源镜像全自动跟随源端
status: active
created: 2026-11-17
updated: 2026-11-17
applies_to:
  - src/quantagent/ingest/writers/wind_page.py
  - src/quantagent/ingest/jobs/wind_paged.py
  - src/quantagent/cli/ingest.py
  - AGENTS.md
supersedes: adr/2026-11-17-wind-revision-auto-replace.md
superseded_by: null
---
# Wind 源镜像全自动跟随源端
## 背景
[修订自动跟随](2026-11-17-wind-revision-auto-replace.md) 只对日行情的七个复权列自动替换，
其余业务字段变化和 `OPMODE=2` 仍要人工 `--replace-existing`。wx2 里的修订量显示这是日常：
`ASHAREDESCRIPTION` 8,500 行（退市写入 `S_INFO_DELISTDATE`）、`ASHAREINCOME` 42 万行、
`ASHAREDIVIDEND` 14.8 万行、`AINDEXMEMBERS` 2.8 万行（调出写入 `S_CON_OUTDATE`）、
`ASHAREPROFITNOTICE` 7.3 万行。按旧规则日更几乎每天停。负责人裁定：全自动。
## 决策
对 Wind 分页写入的全部源表：
1. 已有键业务字段全部相等（只变 `OPDATE`、`OPMODE`、`gsUTime`、`gsCTime`、`mopdate`）：跳过，
   计入 `metadata_skipped`。
2. 业务字段有任何变化：同一事务内按主键 DELETE+INSERT，计入 `replaced`。
3. `OPMODE=2`：按主键删除，计入 `deleted`；本地没有这一键则不发 DELETE。
4. 删除 `--replace-existing` 选项与 `AUTO_REPLACE_COLUMNS`。
保留不变：写库双闸、目标表白名单、SQL 动词白名单（仍禁 UPDATE/MERGE/TRUNCATE/DROP/ALTER）、
每页一事务、写后回读比对、提交或回滚结果未知时停止不重试。三类计数写进 run log。
## 理由
源镜像只反映源端当前状态（[2026-09-17 ADR](2026-09-17-no-source-vintage-archive.md)）。
对源镜像而言，“不覆盖”挡下的是源端的正常修订，起不到防写坏的作用；防写坏靠的是回读与
事务语义，这些都保留。
## 后果
- 源端原地改过的历史值不保留。财报被原地更正后，同一 `as_of` 重算会看到更正后的值，
  由契约的 `pit_grade` 与 `pit_recoverable` 告知下游。
- AGENTS.md §6.4 的“不覆盖既有行”对 Wind 源镜像不再适用，仍适用于 `feature.value`、
  其他 Parquet 产物、`frozen/` 与 Tushare 日历快照写入。
- 用 wx2 游标后 10,463 行只读推演：新增 5,579、替换 4,884、删除 0。
