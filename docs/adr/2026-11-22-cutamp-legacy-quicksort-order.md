---
title: cutamp 复现旧仓 quicksort 的并列顺序，定义版本升到 v2
status: active
created: 2026-11-22
updated: 2026-11-22
applies_to:
  - src/quantagent/features/library/price/cutamp.py
  - tests/integration/test_cutamp_tr_umr_cross_section_live.py
supersedes: null
superseded_by: null
---
# cutamp 复现旧仓 quicksort 的并列顺序，定义版本升到 v2

## 背景

旧仓 `factors/factors.py` 的 `CUTAMP.cal` 用 pandas `sort_values(by='S_DQ_ADJCLOSE')` 排序后切高低两端各 25%。
`sort_values` 默认 quicksort，复权收盘价并列时，谁进切段由 quicksort 的分区与插入过程决定，不是交易日顺序。
新实现 `v1` 按（复权价，交易日）稳定排序。2024-01-05 全截面对拍 `wx2.dbo.stock_cutamp`：本地算出 5,076 只，
无并列的窗口全部一致，有并列的窗口 611 只不一致。改用 quicksort 顺序后 5,076 只全部一致。

## 决策

负责人 2026-11-22 裁定：

1. 排序复现旧仓 quicksort 的顺序。实现是纯 Python 逐行移植 numpy 标量 `aquicksort_`（`SMALL_QUICKSORT=15`），
   排序键用 `float(adj_close)`，与旧仓的 float64 比较一致。
2. `definition_version` 从 `v1` 升到 `v2`。lake 里 34 行 v1 保留不动；同范围重新物化 34 行 v2，
   其中只有 2024-02-02 `000001.SZ` 一行取值不同（v1 -0.4867，v2 -0.6878）。

## 理由

- 迁移以旧行为为基线（AGENTS.md §7.10），并列顺序是旧值的一部分。
- 不直接调 `np.argsort(kind="quicksort")`：numpy 在 x86 AVX-512 上 argsort 走 SIMD 实现，并列顺序随机器变，
  同一输入在 Mac 与公司电脑上可能得到不同值，违反可复现（§7.8）。纯 Python 移植在任何机器上顺序相同。
- 取值变了就是新身份（§7.8），升版本号不覆盖既有行，比原地替换 v1 更易回溯。

## 被否方案

- **登记 611 只为已知例外**：差异可以完全复现，登记例外等于放宽断言。
- **调用 numpy argsort**：跨机器不可复现，见上。
- **保留 v1、替换那 1 行**：要覆盖已提交的 Parquet 行，且同一身份前后取值不同。

## 代价

- 维护一份 numpy 排序算法的移植。窗口最多 20 个元素，递归深度到不了 numpy 的堆排序兜底；
  兜底分支未移植，触发即抛错，不给出对不上旧仓的顺序。
- 对拍只在本机 numpy 2.5.3（arm64 标量路径）上做过；单测用 `np.argsort` 校验移植，wx2 全截面校验结果。

## 推论

- 全截面 golden 的 278 只缺失分两类显式排除：北交所旧代码 234 只（本地描述表已无该代码，`all_a` 本就排除北交所），
  截面日前已退市 44 只（旧表留值，新实现不填充）。其他缺失仍判失败。
- 其他从旧仓移植、内部用 pandas/numpy 默认排序并取切段的因子，迁移时须同样检查并列顺序。
