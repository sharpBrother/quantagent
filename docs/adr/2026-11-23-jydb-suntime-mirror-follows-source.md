---
title: 聚源与朝阳永续源镜像同样跟随源端修订
status: active
created: 2026-11-23
updated: 2026-11-23
applies_to:
  - src/quantagent/ingest/
  - db/migrations/src/
  - AGENTS.md
supersedes: null
superseded_by: null
---
# 聚源与朝阳永续源镜像同样跟随源端修订

## 背景

[Wind](2026-11-17-src-mirror-follows-source.md) 与 [Tushare](2026-11-18-tushare-mirror-follows-source.md)
的源镜像已经按源端修订自动替换。聚源（`src_jydb`）与朝阳永续（`src_suntime`）的采集还没写，
接入前要先定：源端改了已写入的行时，是报错停下（AGENTS.md §6.4 默认），还是跟随。

旧仓 `data/jydb_to_sql.py` 对聚源一直是跟随：按 `(JSID, ID)` 游标增量读取，写入时按 `ID`
先删后插。宏观数据的修订是常态，比如统计局修订前值、同一 `EndDate` 重新发布。

## 决策（负责人 2026-11-23 裁定）

1. `src_jydb` 与 `src_suntime` 的全部源表，与 Tushare 用同一套规则：
   - 目标键不存在：插入，计入 `inserted`。
   - 已有键业务字段全部相等：跳过，计入 `skipped` 或 `metadata_skipped`。
   - 业务字段有任何变化：同一事务内按主键删旧插新，计入 `replaced`。
   - 源端没返回的已写行不删。两个源都没有可靠的删除标记，增量游标缺行不等于源端删除。
2. 只变源端系统列的不算业务变化。系统列包括：聚源的 `JSID`、`UpdateTime`、`XGRQ`、
   `InsertTime`；朝阳永续的 `entrytime`、`updatetime`、`tmstamp`。各表以接入时的列清单为准，
   写进写入规格，由测试固定。
3. 状态类字段是业务字段，变化走替换，不按删除处理。例如聚源 `IndiState`、`ListedState`，
   朝阳永续 `FIN_APPO_RELE_DATE.IS_VALID`。
4. 跟随的前提是有主键。0005 中 `SecuMainAll`、`QT_OSIndexQuote`、`Bond_BondIndexQuote`、
   `QT_GoldTradeMarket` 四张表没有主键，接入前要先按源端核对主键，再补迁移。
   没有主键的表不得启用跟随写入。
5. 其余写入保护照旧：双写闸、目标表白名单、SQL 动词白名单（仍禁 UPDATE、MERGE、TRUNCATE、
   DROP、ALTER）、每页一事务、写后回读比对、提交或回滚结果未知时停止不重试。
   三类计数写进 run log。

## 理由

同 Wind ADR：源镜像只反映源端当前状态（[2026-09-17 ADR](2026-09-17-no-source-vintage-archive.md)）。
对源镜像来说，"不覆盖"挡下的是源端的正常修订；防写坏靠事务、回读和白名单，这些都保留。

## 后果

- 源端原地改过的历史值不保留。宏观数据修订前值、一致预期回补后，同一 `as_of` 重算会看到
  改后的值。PIT 可见日仍取源端的发布字段（聚源 `InfoPublDate`，朝阳 `con_date`、`declare_date`
  等），但值是最新版本，等级与 `pit_recoverable` 在各自的可见性契约里如实标注。
- AGENTS.md §6.4 的例外扩展到聚源与朝阳永续。"不覆盖既有行"仍适用于 `feature.value`、
  其他 Parquet 产物、`frozen/` 与 Tushare 日历快照写入。
