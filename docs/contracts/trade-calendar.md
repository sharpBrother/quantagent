---
title: 交易日历契约
status: active
created: 2026-09-16
updated: 2026-09-17
applies_to:
  - src/quantagent/contracts/schemas/lake/std.trade_calendar.yaml
  - src/quantagent/contracts/visibility/std.trade_calendar.yaml
  - src/quantagent/contracts/schemas/pg/src.tushare.trade_cal.yaml
  - src/quantagent/contracts/visibility/src.tushare.trade_cal.yaml
  - src/quantagent/ingest/sources/tushare/
  - src/quantagent/lake/materialize/trade_calendar.py
---

# 交易日历契约

这是仓库里第一个完整数据集契约，用来把「schema + visibility + 缺规则
fail-closed」这条链路跑通。源镜像来自 Tushare `trade_cal`，标准化层只做
改名与类型，不改口径。

## 数据集

源：`src.tushare.trade_cal`。键是 `(exchange, cal_date)`。`cal_date` /
`pretrade_date` 保持源端 `YYYYMMDD` 字符串；`is_open` 保持源端 0/1。

标准化：`std.trade_calendar`。键是 `(cal_dt, exchange)`。列只有业务字段：
`cal_dt`、`exchange`、`is_open`、`prev_trade_dt`。

不设 `published_at`。Tushare `trade_cal` 一类源端不提供年度休市安排的公告
日；按时间语义，缺失就必须是缺失，不能把采集时间或「上年某日公布」的推测
值写进字段。

`prev_trade_dt` 在历史首日允许为空。空就是空，不用哨兵日期。源端 `is_open`
为 NULL 时标准化 fail-closed，不补 0。

交易所代码保持源端原样（`SSE` / `SZSE` / `CFFEX` 等），标准化层这一步不做
代码映射。映射一旦做了，就无法回答源端到底给了什么。

采集默认交易所是 `SSE`、`SZSE`。`CFFEX` 不在默认窗口里。

## 可见性

规则是 `same_day_close`，等级 A。源表与标准化表同一条规则。

A 的依据：这是交易所官方日历，时间戳属于市场，不是本系统观测。

选用 `same_day_close` 而不是「公告日后立即可见」，是因为源端没有公告日。
更早的可见日需要原生发布时间；没有就停在这条不引入未来信息的下界——该日
收盘后，「这一天是否开市」对市场已是公开事实。

`pit_recoverable: true`：历史上某日是否开市是公开记录，不依赖本系统的修订
版本序列。

`_ingested_at` 只记录本系统何时取到数据，不得当作可见日。

## 上游

`std.trade_calendar.reads` 必须包含 `src.tushare.trade_cal`。源镜像是当前
快照，没有历史版本；物化时 `as_of` 只写入 run log，不按 `cal_dt` 截断，
否则已公布的未来交易日会被当成不可见。PIT 过滤发生在研究读取，不发生在
这一次改名拷贝。

## 入口

- 采集（默认不写库）：`quantagent ingest tushare trade-cal`
- 标准化物化：`quantagent lake materialize trade-calendar --as-of YYYY-MM-DD`
