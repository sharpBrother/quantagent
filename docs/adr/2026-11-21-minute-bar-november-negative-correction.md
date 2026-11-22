---
title: 2025-11-26 分钟行情单条负成交额修正
status: active
created: 2026-11-21
updated: 2026-11-21
applies_to:
  - src/quantagent/ingest/jobs/minprice_corrections.py
  - src/quantagent/ingest/jobs/minprice.py
supersedes: null
superseded_by: null
---

# 2025-11-26 分钟行情单条负成交额修正

MySQL `m20251126` 的 `600289.SH`、`15:00` 一条记录，成交量为 0 手，
成交额为 -43 元。负责人明确要求将该条成交额置 0，整日入库。

仅此 MySQL 原始记录适用：必须恰好一行，且原成交量为 0、原成交额为 -43；
否则停止，不泛化为负数补零。MySQL 不修改，Parquet 中该行成交额保存为 0，
其他字段保留原值；运行日志记录修正前后数值以及修正前后内容摘要。
这一分区不再是逐字段完全等同于 MySQL 的原生镜像，读取时应考虑该例外。
