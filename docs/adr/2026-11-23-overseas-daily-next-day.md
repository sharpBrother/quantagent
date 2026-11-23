---
title: 美国与境外市场日频数据次日可见
status: active
created: 2026-11-23
updated: 2026-11-23
applies_to:
  - src/quantagent/contracts/visibility/src.tushare.us_treasury_yield.yaml
  - docs/domain/pit-rules.md
  - docs/migration/jydb-ingest-plan.md
supersedes: null
superseded_by: null
---
# 美国与境外市场日频数据次日可见

## 背景

`src.tushare.us_treasury_yield` 原来是 `same_day_close`，读取条件是 `trade_date <= as_of`，
沿用旧仓口径，跨时区的严格性交给调用方处理。但美东收盘时已是北京时间次日清晨，
A 股收盘时当日美债还没收盘。所有没有手动滞后的调用方都会因此提前一天看到数据。
研究线 `erp-rate-anchor` 的脚本一直是手动滞后一天读取的。

## 决策（负责人 2026-11-23 裁定）

美国与境外市场的日频数据，交易日 T 的值在北京时间 T+1 才可见，即在下一个 A 股
交易日开盘前可见。契约统一写成 `source_field` + `strict: true`，截止列就是交易日字段：

- `src.tushare.us_treasury_yield`：`trade_date` 严格早于 `as_of`。本 ADR 已改。
- 聚源 `QT_OSIndexQuote`（境外与香港指数）：`TradingDay` 严格早于 `as_of`，接入时按此写
  （见 [交接文档](../migration/jydb-ingest-plan.md)）。港股收盘 16:10，晚于 A 股收盘，同样适用。
  日、韩、澳等收盘早于 A 股的市场会因此晚一天可见，这是偏保守的方向，接受。

FRED／ALFRED 本来就按版本日严格早于 `as_of`，不受影响。

## 影响

- 新仓里 `us_treasury_yield` 的唯一读取方是 `MacroRepository` 和研究脚本
  `notebooks/2026-11-23-erp-rate-anchor.py`。脚本改为直接传信号日作 `as_of`，有效截止日不变，
  重跑后结果 digest 不变。
- 与旧仓 `macro_regime` 的 `trade_date <= asof` 对拍时，会差一天，以本 ADR 为解释。
