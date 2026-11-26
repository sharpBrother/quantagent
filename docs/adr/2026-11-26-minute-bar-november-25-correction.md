---
title: 2026-11-25 分钟行情单条成交量和成交额修正
status: active
created: 2026-11-26
updated: 2026-11-26
applies_to:
  - src/quantagent/ingest/jobs/minprice.py
supersedes: null
superseded_by: null
---

# 2026-11-25 分钟行情单条成交量和成交额修正

MySQL `m20261125` 中 `920608.BJ` 15:00 成交量 -1 手、成交额 18 元，按负责
人此前同类记录的处理要求两项置 0。写前核对唯一记录及原值，变化即停止；不改
MySQL，运行日志记录源摘要和修正前后值。正成交额置零只适用于此条记录。

同日 `920395.BJ` 15:00 成交额 -41 元、成交量 0 手，置零后的当日分钟成交额
与 Wind 日行情均为 2,519,861 元，按既有负成交额小于 0.5% 的规则处理。
