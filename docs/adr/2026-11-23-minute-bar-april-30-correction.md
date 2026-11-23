---
title: 2026-04-30 分钟行情单条成交量和成交额修正
status: active
created: 2026-11-23
updated: 2026-11-23
applies_to:
  - src/quantagent/ingest/jobs/minprice.py
supersedes: null
superseded_by: null
---

# 2026-04-30 分钟行情单条成交量和成交额修正

MySQL `m20260430` 中 `920608.BJ` 15:00 一条记录成交量 -1 手、成交额
422 元。负责人明确要求两项置 0。写前核对唯一记录及原值，源值变化即停止；
不修改 MySQL。该次正成交额置零只适用于此条记录，不推广到其他数据；运行日志
记录完整源摘要及修正前后值。
