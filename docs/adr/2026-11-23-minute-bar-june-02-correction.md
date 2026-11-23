---
title: 2026-06-02 分钟行情单条成交量和成交额修正
status: active
created: 2026-11-23
updated: 2026-11-23
applies_to:
  - src/quantagent/ingest/jobs/minprice.py
supersedes: null
superseded_by: null
---

# 2026-06-02 分钟行情单条成交量和成交额修正

MySQL `m20260602` 的 `920112.BJ` 15:00 一条记录成交量 -1 手、成交额
1037 元。负责人明确要求两项置 0。写前核对唯一记录及原值，源值变化即停止；
不修改 MySQL。此正成交额置零只适用于该记录；运行日志记录源摘要和修正前后值。
