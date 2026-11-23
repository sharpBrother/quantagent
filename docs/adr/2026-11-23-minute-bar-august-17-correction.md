---
title: 2026-08-17 分钟行情两条成交量和成交额修正
status: active
created: 2026-11-23
updated: 2026-11-23
applies_to:
  - src/quantagent/ingest/jobs/minprice.py
supersedes: null
superseded_by: null
---

# 2026-08-17 分钟行情两条成交量和成交额修正

MySQL `m20260817` 的 `920121.BJ` 15:00 记录成交量 -1 手、成交额 1462 元，
`920679.BJ` 15:00 记录成交量 -1 手、成交额 10 元。负责人要求类似既往异常按
惯例处理，两条记录成交量和成交额均置 0。写前核对唯一记录及原值，源值变化
即停止；不修改 MySQL。正成交额置零仅适用于这两条记录，运行日志记录源摘要和
修正前后值。
