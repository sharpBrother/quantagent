---
title: Tushare 源镜像同样全自动跟随源端
status: active
created: 2026-11-18
updated: 2026-11-18
applies_to:
  - src/quantagent/ingest/
  - AGENTS.md
supersedes: null
superseded_by: null
---
# Tushare 源镜像同样全自动跟随源端
## 背景
[Wind 源镜像全自动跟随源端](2026-11-17-src-mirror-follows-source.md) 只覆盖 Wind。负责人指出 Tushare
也经常改历史值，按 §6.4 报错停下会让 Mac 上的日更频繁要人工介入。
## 决策（负责人 2026-11-18 裁定）
1. Tushare 中不带源端版本身份的表（`shibor`、`us_treasury_yield` 等）与 Wind 同规则：
   已有键业务字段全部相等则跳过；有变化则同一事务内按主键删旧插新，计入 `replaced`；
   源端不再返回的已写行不删（Tushare 没有删除标记，接口缺行不等于删除）。
2. 双写闸、目标白名单、按 profile 限定可写 schema、动词白名单、写后回读、状态未知不重试照旧。
3. 带源端版本身份的公开源（ALFRED、WGC、GPR、金十）不适用：修订按新版本追加，旧版本不动。
## 后果
- 源端改过的历史值不保留，同一 `as_of` 重算会看到改后的值，由契约等级告知下游。
- `trade_cal` 的快照写入实施时一并迁到这套规则。
