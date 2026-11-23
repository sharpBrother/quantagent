---
title: 2026-07-06 分钟行情两条成交量和成交额修正
status: active
created: 2026-11-23
updated: 2026-11-23
applies_to:
  - src/quantagent/ingest/jobs/minprice.py
supersedes: null
superseded_by: null
---

# 2026-07-06 分钟行情两条成交量和成交额修正

MySQL `m20260706` 的 `920455.BJ` 15:00 成交量 -1 手、成交额 -41 元，
`920541.BJ` 15:00 成交量 -1 手、成交额 391 元。负责人要求两条记录的成交量
和成交额均置 0。写前核对唯一记录及原值，源值变化即停止；不修改 MySQL。
负成交额仍须满足与日行情差异小于 0.5% 的规则，正成交额置零仅适用于该记录。
运行日志记录源摘要及修正前后值。
