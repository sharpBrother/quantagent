---
title: FRED 的 OECD 德债、日债收益率超精度值按 8 位小数量化
status: active
created: 2026-11-23
updated: 2026-11-23
applies_to:
  - src/quantagent/ingest/sources/macro/fred.py
supersedes: null
superseded_by: null
---
# FRED 的 OECD 德债、日债收益率超精度值按 8 位小数量化

## 背景

FRED 采集器默认拒收超过 8 位小数的值：目标列是 `DECIMAL(18,8)`，超精度通常意味着
源端格式变了，静默截断会让同一份源数据读出不同的值。

研究线 `docs/research/erp-rate-anchor.md` 要用德国、日本 10 年期国债收益率
（`IRLTLT01DEM156N`、`IRLTLT01JPM156N`，OECD MEI 月均）做利率锚的安慰剂。这两条序列的
ALFRED 历史版本里有 `5.1739999999999995`、`7.052380952` 这类值。前者是浮点表示的残留，
后者是 OECD 月均值本身带了 9 位小数。拒收会让整条序列无法入库。

## 决策

负责人 2026-11-23 裁定：只对这两条序列放宽，超过 8 位小数时按 `ROUND_HALF_EVEN`
量化到 8 位后入库。白名单写死在 `fred.py` 的 `_ROUND_8DP_SERIES`。其余序列不变，
超精度仍然报错。

当前值核对（不变量 (c)）与版本行走同一个解析函数，两边量化方式一致，不会因为舍入
产生假冲突。

## 影响

- 收益率单位是百分数，8 位小数对应 1e-8 个百分点，远低于任何研究用途的分辨率。
- 舍入后数值固定，同一份源数据的 digest 不变。
- 可见性规则不变：仍按 ALFRED 首个 `realtime_start` 严格早于 `as_of` 可见。两条序列的
  ALFRED 版本都从 2013-06-03 起，在这之前的观测按 PIT 不可见。
