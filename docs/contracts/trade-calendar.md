---
title: 交易日历契约
status: active
created: 2026-09-16
updated: 2026-11-15
applies_to:
  - src/quantagent/contracts/schemas/lake/std.trade_calendar.yaml
  - src/quantagent/contracts/visibility/std.trade_calendar.yaml
  - src/quantagent/contracts/schemas/pg/src.wind.asharecalendar.yaml
  - src/quantagent/contracts/visibility/src.wind.asharecalendar.yaml
  - src/quantagent/contracts/schemas/pg/src.tushare.trade_cal.yaml
  - src/quantagent/contracts/visibility/src.tushare.trade_cal.yaml
  - src/quantagent/adapters/postgres/src_scan.py
  - src/quantagent/lake/materialize/trade_calendar.py
---

# 交易日历契约

`std.trade_calendar` 由 `src.wind.asharecalendar` 物化。源镜像按 `OBJECT_ID`
保存 Wind 原生行。`TRADE_DAYS` 是开市日，`S_INFO_EXCHMARKET` 保留源端代码。
旧 Tushare 源镜像仍保有独立契约。

标准日历键为 `(cal_dt, exchange)`。每个市场在首尾开市日之间生成自然日，
开市日来自 Wind 集合，区间内其余日期为闭市日。`prev_trade_dt` 是同市场严格
早于当日的最近开市日，覆盖首日为空。源端非法日期、空市场代码或重复开市日
会中止物化。

## 可见性

源与标准日历继续使用 `same_day_close`、等级 A。旧仓用 Wind `TRADE_DAYS`
生成 `trade_cal`，研究入口按 `cal_date` 查询历史窗口或调仓日前开市日。
Wind 源列没有年度日历的公告日。`OPDATE` 记供应商运维时间，
`_ingested_at` 记采集时间，PIT 截止基于业务日。历史上某日是否开市是公开
记录，`pit_recoverable: true`。

物化保存源端覆盖期间的日历快照，`as_of` 记录在运行日志。研究仓储按读取时的
显式 `as_of` 截断。

## 入口

- 源采集使用 `quantagent ingest wind ASHARECALENDAR`。
- 物化使用 `quantagent lake materialize trade-calendar --as-of YYYY-MM-DD`。
