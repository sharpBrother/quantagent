---
title: 研究数据面第一批源镜像
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - db/src_tables.yaml
  - db/migrations/src/
  - src/quantagent/adapters/postgres/
supersedes: null
superseded_by: null
---

# 研究数据面第一批源镜像

PG 研究数据面只存源原生结构。这一批共 **59** 张表，清单在
[`db/src_tables.yaml`](../../db/src_tables.yaml)，DDL 在
`db/migrations/src/`。

收录标准：现役下游（研究代码或真实脚本）有读取。派生表不进 PG。

| schema | 来源 | 张数 |
|---|---|---|
| `src_wind` | Wind | 31 |
| `src_jydb` | 聚源 | 12 |
| `src_suntime` | 朝阳永续 | 6 |
| `src_tushare` | Tushare | 3 |
| `src_macro` | 宏观 ETL（金十 / FRED / WGC / GPR / 日历 / SHIBOR / 美债） | 7 |

每张表另有技术列 `_batch_id` / `_ingested_at` / `_row_hash`，以及旁表
`src_<source>._batch`。`_ingested_at` 不是 PIT 依据。

## 这一批刻意不建

- **零下游 36 张**：只被采集写入或字典里有、现役代码不读。例如 Wind
  `ASHARESECNINDUSTRIES`、`AINDEXFINANCIALDERIVATIVE`，聚源
  `Bond_BaseRateReference`，朝阳 `der_excess_stock`，以及 Tushare 目录里
  的 `fina_*` / `fund_nav` / 同花顺成分股等。
- **仅弱引用**：`ASHAREINSIDEHOLDER`、`ASHAREMJRHOLDERTRADE`、
  `ASHAREPROFITEXPRESS`、`SHIBORPRICES`、`Bond_CBYieldCurveAll`、
  `ED_FixedInvestment`、`IN_ManufacturingPMI`、`con_forecast_citic`、
  `rpt_forecast_stk`。第二批再评估。

字典没有主键的表（如 `fund_share`、部分债券行情）不补造主键。

## 类型映射

SQL Server `datetime` → `timestamp`（无时区，保持源语义）；
`timestamp` / `rowversion` → `bytea`（二进制版本号，不是时间）；
`float` → `double precision`；`tinyint` → `smallint`；`varchar(max)` →
`text`。标识符一律双引号引用，保留 Wind 大写与聚源混用大小写。

宏观 7 张表旧仓没有数据字典，列来自对应 ETL 的目标列，并保留其
`ingested_at` / `record_hash` 等既有列；系统列仍额外加 `_ingested_at`。

结构变更只走编号前向迁移，不写 Alembic，不写回退脚本。
