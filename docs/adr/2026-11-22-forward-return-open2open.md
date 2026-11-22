---
title: 股票前瞻收益按 open-to-open 落 mart，端点停牌不落行
status: active
created: 2026-11-22
updated: 2026-11-22
applies_to:
  - src/quantagent/domain/forward_return.py
  - src/quantagent/contracts/schemas/lake/mart.forward_return.yaml
  - src/quantagent/lake/materialize/forward_return.py
  - tests/integration/test_forward_return_wx2_live.py
supersedes: null
superseded_by: null
---
# 股票前瞻收益按 open-to-open 落 mart，端点停牌不落行

## 背景

旧仓现役生产者只有 `alpha_factory/refresh_forward_returns.py`，写 `wx2.dbo.alpha_factory_forward_return_d`：
`ADJOPEN(T+h+1)/ADJOPEN(T+1) − 1`，T 为信号日，h 按市场开市日计，只落了 5D、10D，全部为 total。
它只检查价格非空、有限、为正，停牌日 Wind 给出等于前收的价格，于是停牌端点被当作有效。
[多周期 ADR](2026-09-19-factor-horizons-and-admission.md) 已定主协议 `oo_5d`、检验 1D/5D/10D/20D。

## 决策

负责人 2026-11-22 裁定：

1. 契约新增 `return_leg`（本次只有 `open2open`，进主键）与 `start_dt`。`event_dt` 是信号日 T，
   `start_dt` = T+1，`end_dt` = T+h+1，均为 SSE 开市日。
2. 四个 horizon 同一公式，后复权开盘价 `S_DQ_ADJOPEN`。`knowledge_dt = end_dt`，`pit_grade` 由两端行情推导。
3. 端点停牌（`S_DQ_TRADESTATUSCODE = 0`）、缺行、缺价或非正价不落行。只做 total，不做超额；不建模可成交性。
4. 旧仓基于 `stock_ratio` 的 1D（起点早一天、缺失补 0）不复现。
5. `DailyPrice` 增加 `adj_open`、`trade_status_code` 两个可空字段，`DailyPriceRepository` 签名不变。

## 理由

- 公式与端点和旧仓现役生产者一致，旧结论可比。
- 停牌前值价格属于隐式填充（AGENTS.md §7.5）；停牌行价格为正，只能靠状态码识别。
- `knowledge_dt = end_dt` 让 `knowledge_dt <= as_of` 天然挡住未实现收益。

## 被否方案

- **沿用旧仓把停牌端点算作有效**：隐式前值填充。
- **把收益腿编码进 `return_kind`**：`return_kind` 只表达 total/excess，混用后 close-to-close 易被误当成 open-to-open。
- **复现旧 1D**：与 5D 不是同一协议，且缺失补 0。

## 代价

- 与旧表相比少了端点停牌的行（29 个样本日 all_a 内约 1%），依赖这些行的旧统计结果会变。
- wx2 对拍只能在 `all_a` 内做：旧表含北交所/新三板旧代码，本地镜像已改码，不可比。

## 推论

`tests/integration/test_forward_return_wx2_live.py` 对拍 29 个样本日的 5D、10D，`all_a` 内其余差异逐行登记在
`forward_return_wx2_explained.json` 并在测试里核验：

- **源价差**：本地与 wx2 端点后复权价不同。部分是 Wind 复权因子重算，部分是 wx2 旧行只存 2 位小数
  （如 000862.SZ 开盘 5.00 × 因子 2.698333，本地 13.4917，wx2 13.49）。用 wx2 价代入新函数可复现旧值。
- **旧表陈旧**：000011.SZ 的旧值与当前任何两端价都对不上，旧行未随价格重算。

旧值按 `numeric(20,10)` 存储，比对时新值先取 10 位小数再按 1e-6 量化，模拟旧表存储精度。
