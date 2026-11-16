---
title: Wind 指数日行情源镜像
status: active
created: 2026-11-16
updated: 2026-11-16
applies_to:
  - src/quantagent/contracts/schemas/pg/src.wind.aindexeodprices.yaml
  - src/quantagent/contracts/visibility/src.wind.aindexeodprices.yaml
  - src/quantagent/ingest/sources/wind/
  - db/migrations/src/0003_wind.sql
---

# Wind 指数日行情源镜像

`src.wind.aindexeodprices` 是 Wind `AINDEXEODPRICES` 的源原生镜像。物理表已在
`0003_wind.sql` 里。2026-11-16 本机该表为 0 行，采集口与 A 股日行情共用
`OPDATE + OBJECT_ID` 游标。

采集列只跟 `wind_db.dbo.AINDEXEODPRICES`：行情字段、`SEC_ID`、`OPDATE`、
`OPMODE`、`gsCTime`、`gsUTime`、`mopdate`。物理表另有 19 个简介列
（`S_INFO_NAME` 到 `S_INFO_INDEXTYPE`），源表没有。这些列不读、不写、不进
内容指纹，写入留 NULL。不因此去采 `AINDEXDESCRIPTION`。

## 可见性

`TRADE_DT` 点事件，`same_day_close`，grade A。旧仓
`MarketDataService.get_index_eod_returns` 写明按交易日过滤，且调用方保证
`end_date <= asof_date`。`fetch_benchmark_ret` 对 `000985.CSI` 同样用
`TRADE_DT` 闭区间。`OPDATE` 与 `_ingested_at` 不是可见日。
