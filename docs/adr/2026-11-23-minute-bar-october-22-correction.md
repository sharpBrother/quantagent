---
title: 2026-10-22 分钟行情单条成交量和成交额修正
status: active
created: 2026-11-23
updated: 2026-11-23
applies_to:
  - src/quantagent/ingest/jobs/minprice.py
supersedes: null
superseded_by: null
---

# 2026-10-22 分钟行情单条成交量和成交额修正

MySQL `m20261022` 的 `920751.BJ` 15:00 记录成交量 -1 手、成交额 37 元。
负责人要求类似既往异常按惯例处理，两项置 0。写前核对唯一记录及原值，源值
变化即停止；不修改 MySQL。正成交额置零仅适用于此条记录，运行日志记录源摘要
和修正前后值。
