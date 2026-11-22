---
title: 2025-10-28 分钟行情单条负值修正
status: active
created: 2026-11-21
updated: 2026-11-21
applies_to:
  - src/quantagent/ingest/jobs/minprice_corrections.py
  - src/quantagent/ingest/jobs/minprice.py
supersedes: null
superseded_by: null
---

# 2025-10-28 分钟行情单条负值修正

MySQL `m20251028` 的 `920014.BJ`、`15:00` 一条记录，成交量为 -1 手，
成交额为 -21 元。负责人明确要求将这两个值置 0，整日入库并继续回填。

仅此 MySQL 原始记录适用：必须恰好一行，且两个原值严格为 -1 和 -21；否则
停止，不泛化为负数补零。MySQL 不修改，Parquet 中该行两个字段保存为 0，
其他字段保留原值；运行日志记录修正前后数值以及修正前后内容摘要。
这一分区不再是逐字段完全等同于 MySQL 的原生镜像，读取时应考虑该例外。
