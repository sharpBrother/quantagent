---
title: 2026-07-08 分钟行情单条负成交量和成交额修正
status: active
created: 2026-11-23
updated: 2026-11-23
applies_to:
  - src/quantagent/ingest/jobs/minprice.py
supersedes: null
superseded_by: null
---

# 2026-07-08 分钟行情单条负成交量和成交额修正

MySQL `m20260708` 的 `920132.BJ` 15:00 记录成交量 -1 手、成交额 -56 元。
负责人要求类似既往异常按惯例处理，两项置 0。写前核对唯一记录及原值，源值
变化即停止；不修改 MySQL。成交额仍须满足与日行情差异小于 0.5% 的规则，
运行日志记录源摘要及修正前后值。
