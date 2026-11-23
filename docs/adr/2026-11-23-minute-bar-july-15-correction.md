---
title: 2026-07-15 分钟行情两条成交量和成交额修正
status: active
created: 2026-11-23
updated: 2026-11-23
applies_to:
  - src/quantagent/ingest/jobs/minprice.py
supersedes: null
superseded_by: null
---

# 2026-07-15 分钟行情两条成交量和成交额修正

MySQL `m20260715` 的 `920112.BJ` 15:00 成交量 -1 手、成交额 28 元；
`920168.BJ` 15:00 成交量 -1 手、成交额 -53 元。负责人要求类似既往异常按惯例
处理，两条记录成交量和成交额均置 0。写前核对唯一记录及原值，源值变化即停止；
不修改 MySQL。负成交额仍须满足与日行情差异小于 0.5% 的规则，正成交额置零仅
适用于该记录。运行日志记录源摘要及修正前后值。
