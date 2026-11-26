---
title: 分钟行情历史与日更来源
status: superseded
created: 2026-11-21
updated: 2026-11-21
applies_to:
  - src/quantagent/ingest/
  - src/quantagent/contracts/
  - orchestration/
supersedes: null
superseded_by: 2026-11-26-minute-bars-mysql-incremental.md
---

# 分钟行情历史与日更来源

负责人确认：MySQL `minprice` 只用于已有历史行情回填；后续新增交易日从
东方财富当日分时接口采集。沿用分钟行情 Parquet 源镜像及 PostgreSQL manifest。
manifest 的 `source_table` 对历史记录保留 MySQL 日表名，对东财记录写
`eastmoney.trends2`，以便区分来源。

两种来源的成交量统一为手、成交额统一为元。样本中平安银行 2026-11-20
09:30 的两边数值相同，且成交额等于价格乘成交量再乘 100；已有东财接口字段
约定也为成交量手、成交额元。其他 OHLC 数据保留各来源原值，不因跨源差异
推测修正。后续若发现单位不符必须停下，不能静默换算。

MySQL 不承担日更或修订跟随。分区已有内容时，内容相同且文件校验成功才跳过；
内容不同即停止，不自动覆盖。东财当日行情需获取完整候选股票域，并通过
交易日、15:00 和股票数量等完整性检查。获取失败不得生成部分分区。

这一裁定替代 [分钟行情 ADR](2026-11-21-minute-bars-in-parquet.md) 中
“MySQL 日更、自动跟随修订”的部分，不改变其存储与 PIT 决策。
