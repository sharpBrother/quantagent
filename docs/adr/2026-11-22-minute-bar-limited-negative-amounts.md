---
title: 分钟行情少量负成交额处理
status: superseded
created: 2026-11-22
updated: 2026-11-22
applies_to:
  - src/quantagent/ingest/jobs/minprice_corrections.py
  - src/quantagent/ingest/jobs/minprice.py
supersedes: null
superseded_by: 2026-11-22-minute-bar-negative-amount-daily-check.md
---

# 分钟行情少量负成交额处理

负责人裁定：MySQL 历史分钟行情每天最多 10 条负成交额时，将这些记录的
成交额置 0 后回填；超过 10 条则停止。仅适用于 MySQL 历史回填，不自动
修正东财数据或任何其他字段，负成交量等其他异常仍按原校验停止。

MySQL 源表不修改；Parquet 的相应成交额保存为 0，其余字段保持源值。
运行日志逐条记录代码、时间、修正前后值，并保存原始输入与修正后内容摘要。
读者应注意这些分区不再与源表逐字段完全一致。此前逐条确认的修正规则
仍严格核验原始记录；本裁定替代此前“不泛化负成交额置零”的限制。
