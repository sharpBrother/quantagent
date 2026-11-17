---
title: Wind A 股交易日历源镜像
status: active
created: 2026-11-15
updated: 2026-11-15
applies_to:
  - db/migrations/src/0008_wind_asharecalendar.sql
  - src/quantagent/ingest/sources/wind/tables.py
---

# Wind A 股交易日历源镜像

`wind_db.dbo.ASHARECALENDAR` 是新的 A 股日历来源。
`src_wind."ASHARECALENDAR"` 按 `OBJECT_ID` 保存源记录及采集批次信息。
历史初始化与增量共用 `quantagent ingest wind ASHARECALENDAR`，从最近一次成功提交
的 `OPDATE + OBJECT_ID` 继续。首次采集前已确认源表的 `OPDATE` 无空值。
干跑默认一页。写入须同时打开写闸并传 `--write-db`；
源修订与删除全自动跟随源端，见 [ADR](../adr/2026-11-17-src-mirror-follows-source.md)。

`TRADE_DAYS` 是业务日期，`OPDATE` 是采集游标。日历物化生成闭市日与上一交易日。研究读取经 `std.trade_calendar` 执行 PIT 过滤。
