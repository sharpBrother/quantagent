---
title: Wind 第一批 14 张源镜像的可见性规则
status: active
created: 2026-11-17
updated: 2026-11-17
applies_to:
  - src/quantagent/contracts/schemas/pg/
  - src/quantagent/contracts/visibility/
---
# Wind 第一批 14 张源镜像的可见性规则

这 14 张 Wind 源表已接入采集。每张表有一份 schema YAML 和一份 visibility YAML，
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
## D 组：两融、停牌、基金持仓、分红
| 表 | dataset | 可见性字段 | rule | grade | temporal_kind |
|---|---|---|---|---|---|
| ASHAREMARGINTRADE | `src.wind.asharemargintrade` | `TRADE_DT` | `same_day_close` | A | `point_event` |
| ASHARETRADINGSUSPENSION | `src.wind.asharetradingsuspension` | `S_DQ_SUSPENDDATE` | `same_day_close` | B | `point_event` |
| CHINAMUTUALFUNDSTOCKPORTFOLIO | `src.wind.chinamutualfundstockportfolio` | `ANN_DATE` | `source_field` | A | `period_with_revision`，`period_fields: [F_PRT_ENDDATE]` |
| ASHAREDIVIDEND | `src.wind.asharedividend` | `ANN_DT` | `source_field` | B | `period_with_revision`，`period_fields: [REPORT_PERIOD]` |
- **ASHAREMARGINTRADE（A）**：两融明细。旧仓 `factors/factor_etf_margin.py` 按 `TRADE_DT` 闭区间读取，ETF 四象限推送按 `TRADE_DT` 等值读取，含当日。收盘后公布。
- **ASHARETRADINGSUSPENSION（B）**：停牌事件。旧仓唯一读取是 `factors/factor_etf.py`，按 `S_DQ_SUSPENDDATE` 区间与等值过滤。源表无公告日。`S_DQ_RESUMPDATE` 在复牌后原地补写，按停牌日读取时不能用复牌日判断当时状态，故标 B。
- **CHINAMUTUALFUNDSTOCKPORTFOLIO（A）**：基金持仓。旧仓唯一读取是 `alpha_factory/data_gateway.py` 的 `get_fund_high_dividend_holdings`，用 `ANN_DATE < adj_date`。数据集规则按财报先例取 `ANN_DATE <= as_of`。调仓日当天不含，由调用方把 `as_of` 设为前一日表达。
- **ASHAREDIVIDEND（B）**：分红。旧仓研究读取 `factors/factor_fundamental.py` 与宽基配置策略均按 `ANN_DT` 截止。`EX_DT` 只出现在采集修复与审计脚本中。分红从预案到实施在同一行原地更新，`ANN_DT` 随进度后移，`EX_DT` 等字段事后补写，历史时点的预案状态不可恢复，故标 B。
