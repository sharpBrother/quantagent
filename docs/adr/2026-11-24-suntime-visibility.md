---
title: 朝阳永续接入范围与一致预期可见性
status: active
created: 2026-11-24
updated: 2026-11-24
applies_to:
  - docs/migration/suntime-ingest-plan.md
  - docs/domain/pit-rules.md
  - src/quantagent/contracts/visibility/
supersedes: null
superseded_by: null
---
# 朝阳永续接入范围与一致预期可见性

## 背景

朝阳永续（`src_suntime`）接入前核对 wx2 与旧仓代码，发现三件事：

- `con_forecast_stk_ttm` 不是供应商的表。旧仓 `data/wind_to_sql_am.py` 用 `con_forecast_stk` 加 Wind 财报
  算出它，按 `nd` 删后重插，表里也没有 `tmstamp`。
- `rpt_earnings_adjust` 的入库常晚于研报日期 `current_create_date`。2026-09 以来只有 42% 当天入库，
  最长晚 60 天；2019 年 6 月平均晚 165 天。旧仓按研报日期过滤，回测会提前看到一部分调整。
- `con_forecast_stk` 在 2018 年以前的快照是事后回补的，入库时间比快照日期晚几年。
  2018 年起是快照当天 17 到 20 点入库。

旧仓对一致预期的口径在多处一致：`con_date <= trade_date`，`trade_date` 指收盘后的观察日，
信号下一交易日执行（`docs/RUNBOOK/style-rotation-dimension-refresh-contract.md`、
`REVIEW-0111`、`agent_style_rotation/data_gateway.py`、`alpha_factory/etf/gateway.py`、
`core/raw_loader.py`）。旧仓没有 PIT 等级的概念，也没有区分回补的历史。

## 决策（负责人 2026-11-24 裁定）

1. `con_forecast_stk_ttm` 不作为源镜像同步。0006 建的空表留着，不写入。以后要用就在 `features` 层用源表重算。
2. `rpt_earnings_adjust` 只建镜像，不写可见性契约。没有契约，引擎会拒绝对它做 PIT 查询。
   研究侧要用时，再在"研报日期"和"研报日期与入库日期取晚者"之间选定。
3. `con_forecast_stk`、`con_forecast_roll_stk`、`der_diver_stk` 按旧仓口径：
   `source_field`、`field=con_date`、非 strict。等级为 A：`con_date` 是供应商原生的快照日期，
   符合 pit-rules 对 A 级的定义。rationale 写明 2018 年以前是供应商回补，并且源端会改写历史行。
4. 全量回填直接从源库 `suntime_db` 读，不从 wx2 导入。

## 后果

- 2018 年以前的一致预期快照可能用到了当时还没入库的研报。这个风险记在契约 rationale 里，
  pit_report 展示时随之呈现，不另降等级。
- `rpt_earnings_adjust` 在有契约之前不能进入任何因子或回测。
