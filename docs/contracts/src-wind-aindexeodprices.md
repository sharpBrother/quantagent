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

采集列和物理表都跟 `wind_db.dbo.AINDEXEODPRICES`：行情字段、`SEC_ID`、`OPDATE`、
`OPMODE`、`gsCTime`、`gsUTime`、`mopdate`。另外只保留 `_batch_id`、`_ingested_at`、
`_row_hash`。`0003_wind.sql` 已应用，多建的 19 个简介列由
`0009_aindexeodprices_source_columns.sql` 在表为空时删掉重建。不采
`AINDEXDESCRIPTION`。

## 可见性

`TRADE_DT` 点事件，`same_day_close`，grade A。旧仓
`MarketDataService.get_index_eod_returns` 写明按交易日过滤，且调用方保证
`end_date <= asof_date`。`fetch_benchmark_ret` 对 `000985.CSI` 同样用
`TRADE_DT` 闭区间。`OPDATE` 与 `_ingested_at` 不是可见日。
