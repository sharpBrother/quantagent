---
title: Wind 第一批 10 张源镜像的可见性规则
status: active
created: 2026-11-17
updated: 2026-11-17
applies_to:
  - src/quantagent/contracts/schemas/pg/
  - src/quantagent/contracts/visibility/
---
# Wind 第一批 10 张源镜像的可见性规则

这 10 张 Wind 源表已接入采集。每张表有一份 schema YAML 和一份 visibility YAML，
`doc_ref` 都指向本页。规则的判定方法见 [`../domain/pit-rules.md`](../domain/pit-rules.md)。
表的 PG 物理结构在 `db/migrations/src/`，列清单由 `src_targets.py` 与
`ingest/writers/tables.py` 的 `native_columns` 决定。

所有数据集都是 `keys: [OBJECT_ID]`、`reads: []`、`layer: pg`、`pit_recoverable: true`。

## A 组：交易所日频，点事件

| 表 | dataset | 可见性字段 | rule | grade |
|---|---|---|---|---|
| ASHAREMONEYFLOW | `src.wind.asharemoneyflow` | `TRADE_DT` | `same_day_close` | A |
| ASHAREEODDERIVATIVEINDICATOR | `src.wind.ashareeodderivativeindicator` | `TRADE_DT` | `same_day_close` | A |
| AINDEXVALUATION | `src.wind.aindexvaluation` | `TRADE_DT` | `same_day_close` | A |
| AINDEXINDUSTRIESEODCITICS | `src.wind.aindexindustrieseodcitics` | `TRADE_DT` | `same_day_close` | A |
| ASHAREMARGINTRADESUM | `src.wind.asharemargintradesum` | `TRADE_DT` | `same_day_close` | A |

`temporal_kind: point_event`，`event_field: TRADE_DT`。旧仓现役下游按 `TRADE_DT`
点查或闭区间读取，调用方保证 `end <= as_of`。收盘后当日公开。`OPDATE` 与
`_ingested_at` 不作为可见日。

## B 组：财报与财务指标，期间加修订

| 表 | dataset | 可见性字段 | rule | grade |
|---|---|---|---|---|
| ASHAREINCOME | `src.wind.ashareincome` | `ANN_DT` | `source_field` | A |
| ASHARECASHFLOW | `src.wind.asharecashflow` | `ANN_DT` | `source_field` | A |
| ASHAREBALANCESHEET | `src.wind.asharebalancesheet` | `ANN_DT` | `source_field` | A |
| ASHAREFINANCIALINDICATOR | `src.wind.asharefinancialindicator` | `ANN_DT` | `source_field` | A |

`temporal_kind: period_with_revision`，`period_fields: [REPORT_PERIOD, STATEMENT_TYPE]`。
旧仓下游按 `ANN_DT <= as_of` 取数，空公告日不可见，同报告期留最后一次公告。
调仓日当天公告可见。**不写 fallback**：不用法定披露日推断缺失的公告日。

## C 组：业绩预告

| 表 | dataset | 可见性字段 | rule | grade |
|---|---|---|---|---|
| ASHAREPROFITNOTICE | `src.wind.ashareprofitnotice` | `S_PROFITNOTICE_DATE` | `source_field` | A |

`temporal_kind: period_with_revision`，`period_fields: [S_PROFITNOTICE_PERIOD]`。
旧仓下游按 `S_PROFITNOTICE_DATE` 过滤，公告日 `<= as_of` 可见。
