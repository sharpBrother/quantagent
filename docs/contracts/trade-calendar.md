---
title: 交易日历契约
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/contracts/schemas/lake/std.trade_calendar.yaml
  - src/quantagent/contracts/visibility/std.trade_calendar.yaml
---

# 交易日历契约

这是仓库里第一个完整数据集契约，用来把「schema + visibility + 缺规则
fail-closed」这条链路跑通。数据尚未采集；契约先于实现存在。

## 数据集

`std.trade_calendar`。键是 `(cal_dt, exchange)`，时间形态是 `point_event`。

列只有业务字段：`cal_dt`、`exchange`、`is_open`、`prev_trade_dt`。

不设 `published_at`。Tushare `trade_cal` 一类源端不提供年度休市安排的公告
日；按时间语义，缺失就必须是缺失，不能把采集时间或「上年某日公布」的推测
值写进字段。

`prev_trade_dt` 在历史首日允许为空。空就是空，不用哨兵日期。

交易所代码保持源端原样（`SSE` / `SZSE` / `CFFEX` 等），标准化层这一步不做
代码映射。映射一旦做了，就无法回答源端到底给了什么。

## 可见性

规则是 `same_day_close`，等级 A。

A 的依据：这是交易所官方日历，时间戳属于市场，不是本系统观测。

选用 `same_day_close` 而不是「公告日后立即可见」，是因为源端没有公告日。
更早的可见日需要原生发布时间；没有就停在这条不引入未来信息的下界——该日
收盘后，「这一天是否开市」对市场已是公开事实。

`pit_recoverable: true`：历史上某日是否开市是公开记录，不依赖本系统的修订
版本序列。

## 尚未声明的上游

`reads` 为空。源表契约（例如 `src.tushare_trade_cal`）在采集落地时再补，
届时本数据集必须加上对应的 `reads:`，否则血缘图会把日历假装成无上游的根。
