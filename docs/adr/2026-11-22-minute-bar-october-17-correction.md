---
title: 2025-10-17 分钟行情 45 条负成交额修正
status: active
created: 2026-11-22
updated: 2026-11-22
applies_to:
  - src/quantagent/ingest/jobs/minprice_corrections.py
  - src/quantagent/ingest/jobs/minprice.py
supersedes: null
superseded_by: null
---

# 2025-10-17 分钟行情 45 条负成交额修正

MySQL `m20251017` 有 45 条负成交额记录，负责人查看后要求置 0 并入库。
该日是每日最多 10 条自动修正规则的一次明确例外，不提高其他日期的上限。

写入前必须核对 45 条负成交额记录的代码、时间及全部原始行情字段的固定
摘要；数量或内容变化即停止。MySQL 不修改，Parquet 仅把这 45 条的成交额
置 0，其他字段保持原值。运行日志逐条记录修正前后值与输入、输出摘要；
这一分区与原源表不逐字段完全一致。
