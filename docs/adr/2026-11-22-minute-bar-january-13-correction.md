---
title: 2026-01-13 分钟行情 75 条负成交额修正
status: active
created: 2026-11-22
updated: 2026-11-22
applies_to:
  - src/quantagent/ingest/jobs/minprice_corrections.py
  - src/quantagent/ingest/jobs/minprice.py
supersedes: null
superseded_by: null
---

# 2026-01-13 分钟行情 75 条负成交额修正

MySQL `m20260113` 有 75 条负成交额记录，负责人要求按照之前相同方式置 0
并继续回填。该日是每日最多 10 条自动修正规则的一次明确例外，不提高其他日期的上限。

写入前必须核对 75 条负成交额记录的代码、时间及全部原始行情字段的固定
摘要；数量或内容变化即停止。MySQL 不修改，Parquet 仅把这 75 条的成交额
置 0，其他字段保持原值。运行日志逐条记录修正前后值与输入、输出摘要；
这一分区与原源表不逐字段完全一致。
