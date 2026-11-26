---
title: event_delta_roe 迁移口径——Wind ROE 优先/profit 重算二分支、股东权益潜在前视、快照时差
status: active
created: 2026-11-26
updated: 2026-11-26
applies_to:
  - src/quantagent/features/library/fundamental/event_delta_roe.py
  - src/quantagent/features/panel/event_delta_roe.py
  - src/quantagent/adapters/postgres/fundamental.py
  - tests/golden/test_event_delta_roe_wx2.py
supersedes: null
superseded_by: null
---
# event_delta_roe 迁移口径

## 背景

`event_delta_roe`（盈余公告 ROE 同比变化，`pf_single_event_delta_roe_1_mean_pos`，方向 +1）
迁移自旧仓 `factors/factor_event_2.py`。定义：当期 ROE − 去年同期 ROE。是三事件因子中最复杂的，
涉及 Wind 财务指标、股东权益、跨期利润三类输入的二分支逻辑。`event_dt = declare_date`
（不依赖行情，与 event_sue 同，区别于 event_aog）。

## 决策

### 1. Wind ROE 优先 / profit 重算二分支（复现旧代码）

- `roe_last`（去年同期 ROE）：`ASHAREFINANCIALINDICATOR.S_QFA_ROE`，`REPORT_PERIOD = period_ly`、
  `ANN_DT <= declare_date`，按 ANN_DT 排序取最后一行。**`period_ly` 不在结果中则整个事件不产值**。
- 当期 `roe`：`period` 在结果中且 `S_QFA_ROE` 非空 → 用 Wind 值（主路径，覆盖绝大多数股票）；
  否则用 profit 重算 `roe = 100 * profit_q / eqt`：`eqt` 上一期股东权益（÷10000）、`profit_q`
  单季利润（Q1 用累计，否则 `profit − get_profit(上一期)`）。

验证：600000.SH 2024Q1 Wind 分支 `2.373834 − 2.242767 = 0.131` 与 wx2 一致。

### 2. 股东权益不按 declare_date 截止——潜在前视，复现旧行为并登记

旧代码 `get_shrhldr_eqt` 只按 `REPORT_PERIOD` 取股东权益，**不按 ANN_DT 截止**（尽管
`ASHAREBALANCESHEET` 有 ANN_DT 列）。这是潜在前视：若事件 declare_date 早于股东权益表公告日，
会用到未来数据。但批量读取的 `as_of` 截止（契约 ANN_DT grade A）已隐含一层过滤；panel 不再
对 eqt 按事件 declare_date 裁剪，**复现旧行为**，在此登记为已知口径。重算分支仅在 Wind ROE
缺失时触发（少数股票），故此潜在前视影响面有限。若要修正需负责人裁定，不在本次迁移顺手改。

### 3. 同源读取细节（复现）

- `get_profit`：`fin_income_gen` 该期归母净利，`report_type desc` 取首行（1003 调整版优先
  于 1001），÷10000。复用 `fin_income_gen` 利润序列，不建新 adapter。
- `get_shrhldr_eqt`：`STATEMENT_TYPE = 408001000`（合并报表）。`TOT_SHRHLDR_EQY_EXCL_MIN_INT` ÷10000。
- 旧代码取数用 `.iloc[0,0]` / `.iloc[-1]` 且无完整 ORDER BY 保障，多修订行时物理行序影响结果，
  本身非确定——这是 golden 差异的来源之一。

### 4. 域判定 / 聚合 / 空批次：与 event_sue 一致

域判定用 declare 后首个交易日（裁定 B1，非交易日 declare 无截面）；同 `(declare_date, asset_id)`
AVG 聚合（复现下游消费粒度）；`candidate_count` 区分合法空/异常空（非披露期无事件合法空）。

## golden 对拍结果

fixture `tests/golden/market_data/event_delta_roe/20240430.json`（wx2 1804 行）。1324 只股票
**match=1306（98.6%）+ 快照时差 18（1.4%）+ 缺失 0**。差异根因：

1. **财报修订快照时差**（主因）：diff 大的股票（002424/300379/300208 等）均有 1003 调整版——
   wx2 用计算时点快照，PG 是当前最新镜像，与 event_sue 同根因。
2. **重算分支对快照更敏感**：负股东权益极端股（300208 资不抵债）的 profit/eqt 快照差异被放大，
   delta_roe 绝对值可达 ±数百。
3. **旧代码 `iloc[0,0]` 无 ORDER BY** 的物理行序非确定性。

算法主路径正确（98.6% + Wind 分支端到端验证），差异可解释，测试断言一致率下限 90%。

## 物化与日更

- 全历史回填：2018-01 至 2026-10，统一 as_of=2026-11-26（行数见 roadmap）。
- 04:10 日更：就绪输入 `(ashareeodderivativeindicator,)`（不依赖行情，仅需 all_a 域）；
  血缘 deps = 财报三源 + ROE（`src_wind_asharefinancialindicator`）+ 股东权益
  （`src_wind_asharebalancesheet`）采集资产。
