---
title: 2026-01-22 分钟行情单条负成交量和成交额修正
status: active
created: 2026-11-22
updated: 2026-11-22
applies_to:
  - src/quantagent/ingest/jobs/minprice.py
supersedes: null
superseded_by: null
---

# 2026-01-22 分钟行情单条负成交量和成交额修正

MySQL `m20260122` 的 `002485.SZ` 15:00 一条记录，成交量 -1 手、成交额
-28 元。负责人要求两项均置 0 后入库。写前必须精确匹配唯一记录及原值，源值
变化则停止；不修改 MySQL。成交额仍需通过现行逐股票日行情差异小于 0.5% 的
校验，其他负成交额遵循同一规则。日志记录完整源摘要和修正前后值。
