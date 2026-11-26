---
title: 东财分钟行情使用 Wind 在市股票采集名单
status: active
created: 2026-11-25
updated: 2026-11-25
applies_to:
  - src/quantagent/domain/ports/universe.py
  - src/quantagent/adapters/postgres/universe.py
  - src/quantagent/ingest/jobs/eastmoney_minute.py
supersedes: null
superseded_by: null
---

# 东财分钟行情使用 Wind 在市股票采集名单

负责人决定分钟行情的当日股票名单使用 Wind `ASHAREDESCRIPTION`，不依赖
东财股票列表接口。复用股票池适配器已加载的上市信息：上市日不晚于采集日，
退市日为空或晚于采集日，交易所为 SSE、SZSE 或 BSE。包含上市首日股票和
北交所股票；不沿用 `all_a` 股票池的上市满一年、排除北交所、市值观测条件。

Wind 描述表是当前态快照，不具有历史版本；该接口只用于当日采集选股，不是 PIT
研究股票池，不可用它证明历史日期可见性。数据源不完整或采集失败时仍停止整日
分区登记，不填充、不跳过请求失败的股票。
