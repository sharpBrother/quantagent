---
title: tr_umr 升 v2，窗口内缺输入不产值
status: active
created: 2026-11-24
updated: 2026-11-24
applies_to:
  - src/quantagent/features/library/price/tr_umr.py
  - tests/integration/test_cutamp_tr_umr_cross_section_live.py
supersedes: null
superseded_by: null
---
# tr_umr 升 v2，窗口内缺输入不产值

## 背景

旧仓 `factors/guosen_umr.py:421` 按半衰期权重对"风险系数 × 超额收益"求和时用 pandas `.sum()`，跳过 NaN 乘积，
分母仍是满窗口权重和，等于把缺失项当作 0 贡献。新仓 `v1` 用 `nansum` 复现了这一点，与 wx2 一致，
但违反 AGENTS.md §7.5（缺失不补 0）。

## 决策

负责人 2026-11-22 裁定：`definition_version` 升 `v2`。最后 60 个风险系数或超额收益中任一项非有限，该截面不产值。
其余公式、窗口与 `PARAM_HASH` 不变。lake 里 34 行 `v1` 保留；同范围补写 34 行 `v2`，取值与 `v1` 全部相同。

## 理由

缺失当 0 会把"不知道"写成"无贡献"，因子值看起来有定义，实际上被截断。与 cutamp、分钟因子的假 0 处理保持同一原则。

## 被否方案

- **保留 v1 并在文档注明**：已知违反 §7.5 的值继续进长表。
- **原地改 v1**：同一身份前后取值可能不同。

## 代价

- 窗口内有停牌、缺行或指数缺收益的股票会少一些截面值。2024-01-05 全截面上没有出现这类股票，4,858 只仍与 wx2 一致。
  其他日期未做全截面对拍，差异规模未知；集成测试已把"wx2 有值、v2 因窗口内缺输入不产值"列为独立类别并逐只核实。
- 超额收益只需最后 60 日；第 0–8 日只用于风险项的滚动均值，这一边界与旧仓 `_calc_umr` 一致。
