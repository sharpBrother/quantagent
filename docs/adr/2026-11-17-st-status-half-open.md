---
title: ST 状态按左闭右开区间判断
status: active
created: 2026-11-17
updated: 2026-11-17
applies_to:
  - src/quantagent/domain/universe/st.py
  - src/quantagent/domain/ports/st.py
  - src/quantagent/adapters/postgres/st.py
supersedes: null
superseded_by: null
---
# ST 状态按左闭右开区间判断
## 背景
旧仓 10 处读取 `ASHAREST`，边界不一致：`alpha_factory/data_gateway.py:1261` 用 `ENTRY_DT < 调仓日`；
`core/universe_provider.py` 的窗口把摘帽当天算作 ST；其余 5 处当日判定
（`strategy/growth_stock.py:368`、`strategy/growth_stock_2.py:287`、`factors/factor_etf.py:325`、
`factors/factor_fundamental.py:161`、`data/宽基指数配置策略2.py:322`）都是
`ENTRY_DT <= dt AND (REMOVE_DT IS NULL OR dt < REMOVE_DT)`。
## 决策（负责人 2026-11-17 裁定）
1. dt 当日 ST：`ENTRY_DT <= dt < REMOVE_DT`，REMOVE_DT 为空即仍在 ST。戴帽当天算，摘帽当天不算。
2. 源表不配 visibility，只经 `StStatusRepository.st_codes_at(as_of, dt)` 读，与股票池同样读取时计算。
   `dt > as_of` 报错；同一代码多段区间重叠是 ST 类型切换，按代码去重；空集合法。
3. 等级 B：可见日按 `ENTRY_DT`，源表有 `ANN_DT` 但旧仓无一处使用。
4. “近 90 天曾 ST”是策略过滤，不在数据层，由调用方组合。
## 对拍
`tests/golden/test_st_status_legacy.py`：wx2 快照 2010-01 至 2026-10 共 202 个月末，与旧仓多数口径 SQL
逐日一致。把边界换成 `ENTRY_DT <` 有 54 天不一致，换成摘帽日含当天有 30 天不一致，fixture 能区分。
