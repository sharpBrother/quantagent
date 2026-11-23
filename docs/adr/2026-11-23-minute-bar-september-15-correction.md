---
title: 2026-09-15 分钟行情三条成交量和成交额修正
status: active
created: 2026-11-23
updated: 2026-11-23
applies_to:
  - src/quantagent/ingest/jobs/minprice.py
supersedes: null
superseded_by: null
---

# 2026-09-15 分钟行情三条成交量和成交额修正

MySQL `m20260915` 有三条 15:00 的 -1 手记录，成交额均为正：`920121.BJ` 205 元、
`920166.BJ` 2 元、`920168.BJ` 542 元。类型与 2026-08-24 的三条记录相同，按负责人
“类似少量负成交量按惯例处理”的指示执行，成交量和成交额均置 0，不涉及负成交额
的日行情对比。写前核对唯一记录及原值，源值变化即停止；不修改 MySQL。运行日志
记录源摘要及修正前后值。
