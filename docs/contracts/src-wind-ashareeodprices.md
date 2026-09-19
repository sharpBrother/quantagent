---
title: Wind A 股日行情源镜像
status: active
created: 2026-09-19
updated: 2026-09-19
applies_to:
  - src/quantagent/contracts/schemas/pg/src.wind.ashareeodprices.yaml
  - src/quantagent/contracts/visibility/src.wind.ashareeodprices.yaml
  - src/quantagent/ingest/sources/wind/
  - src/quantagent/ingest/jobs/wind_paged.py
  - src/quantagent/ingest/writers/wind_page.py
  - db/migrations/src/0003_wind.sql
---

# Wind A 股日行情源镜像

`src.wind.ashareeodprices` 是 Wind `ASHAREEODPRICES` 的源原生镜像。PG 表名
保持大写；契约 dataset 小写。键是 `OBJECT_ID`。字段名、类型、语义与
`wind_db` 一致，采集层不做复权或交易状态口径加工。

`S_DQ_TRADESTATUS` 仍做 latin1→gbk 字段级修复：这是源端编码事故，不是业务
加工，与旧仓 `update_stock_daily_paged` 同一条。

## 可见性

`TRADE_DT` 点事件，`same_day_close`，grade A。旧仓现役下游对交易所日行情
按 `TRADE_DT` 点查或闭区间、调用方保证 `end<=as_of`，多处一致，见
[../domain/pit-rules.md](../domain/pit-rules.md)。

`OPDATE` 是 Wind 运维时间，不是行情可见日。`_ingested_at` 更不是。修订行
（`OPMODE=1`）仍按该行 `TRADE_DT` 可见；源端未提供独立发布时间。

## 采集游标

历史回填与日更共用 `quantagent ingest wind ASHAREEODPRICES`。分页键是
`OPDATE + OBJECT_ID`，检查点写在 `src_wind._batch.source_cursor`，**不**
用目标表 `max(OPDATE)`，也**不**用 `TRADE_DT` 窗口。同一毫秒内后续
`OBJECT_ID` 必须能续上；提交成功才推进游标。

`OPMODE=2` 与内容变化的已有键默认 fail-closed，必须显式
`--replace-existing`（DELETE+INSERT，禁止 UPDATE/MERGE）。
