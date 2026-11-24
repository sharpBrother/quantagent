---
title: 资金流三因子第二批：缺失严格口径，wx2 与本地的差异以本地为准，股票池逐截面日取 all_a
status: active
created: 2026-11-24
updated: 2026-11-24
applies_to:
  - src/quantagent/features/library/money_flow/
  - src/quantagent/features/library/umr_math.py
  - src/quantagent/features/library/_legacy_sort.py
  - src/quantagent/features/panel/money_flow.py
  - src/quantagent/domain/ports/money_flow.py
  - src/quantagent/adapters/postgres/money_flow.py
  - src/quantagent/cli/moneyflow_materialize.py
  - tests/unit/cli/test_moneyflow_membership.py
  - tests/integration/test_moneyflow_factors_wx2_live.py
  - tests/golden/market_data/moneyflow_factors/
supersedes: null
superseded_by: null
---
# 资金流三因子第二批：缺失严格口径，wx2 差异以本地为准，股票池逐截面日取 all_a

> 调度方建议，延续负责人 2026-11-22、11-24 的缺失原则。未经负责人裁定。

## 背景

Current-20 第二批的 `abso_umr`、`moneyflowh`、`actlargemedcut`（旧仓 `factors/factors.py`、`guosen_umr.py`）。
上一版草稿把三类问题列为待裁定：窗口内缺失的口径，2023-12-13 的 SH 资金流快照，2022-06 等旧表陈旧时段。

## 决策

1. **缺失与分母为 0**：窗口内任一所需输入缺失，或分母为 0，不产值（§7.5，与 `tr_umr` v2 相同）。
   旧 wx2 有值而本仓无值时，golden 把这类行记为「已裁定」，并同时证明两件事：本地窗口确有缺失，且旧 pandas 语义
   （`sum()`、`nansum`、`dropna()` 跳过缺失）模拟出的值等于旧值。
2. **wx2 与本地的资金流差异以本地为准**。本仓不产出 wx2 的旧值。golden 把 wx2 中与本地不同的资金流行存入
   `tests/golden/market_data/moneyflow_factors/wx2_source_rows.json`（9 个字段，NULL 保留，wx2 无行存 null）。
   替换后，本仓同一计算函数，或旧语义模拟，必须复现旧值。两条路径任一成立即记为「源数据差异」。
3. **不可复现时段不追查、不进 golden**。golden 截面日只取抽样中三因子都达标的日期（见下）。
4. **股票池逐截面日取 all_a**。读取范围取区间内各截面日成员的并集，输出只保留截面日当天属于 all_a 的行。
   不再用 `end` 日成员回填整个区间（会造成幸存者偏差）。分钟因子同此口径。前瞻收益 CLI 仍用 `end` 日成员，未改。

## 抽样与可复现区间

每月取第一个 15 日及以后的开市日（2021-10 至 2026-11，共 62 个）。abso_umr 另取 2018-05 起每季度一个（14 个）。
一致率 = 双方有值且相等 / (双方有值且相等 + 其他)，分母排除已裁定与源数据差异。达标：一致率 ≥ 99%，且分母不少于
wx2 非空行的一半。

- abso_umr 不可复现：2023-04 至 2023-10、2024-01 至 2024-04。原因是窗口跨越下面的 wx2 重写日。
- moneyflowh 不可复现：2021-12、2022-06 至 2022-08、2022-10 至 2022-11、2023-04、2023-06、2023-08、2024-01、2025-07、2025-09。
- actlargemedcut 不可复现：2021-12、2022-07 至 2022-08、2022-11、2025-07、2025-09。
- 2021-10-15 的 moneyflowh、actlargemedcut 在 wx2 中无行。

golden 截面日：2023-03-15、2023-12-15、2024-05-15、2025-10-15。其中 2023-12-15 的 abso_umr 窗口跨 2023-12-13 快照，
2025-10-15 窗口内 1238 只股票除权。四天的三因子「其他」都为 0。

观察到的 wx2 `ASHAREMONEYFLOW` 批量重写（不追查）：2023-03-20、2023-06-02、2023-08-01、2024-01-08 当日行几乎全部与本地
不同，OPDATE 为当日（2024-01-08 只有 2827 行）；2023-12-13 有 5084 行 OPDATE 为当日，其中 2242 行与本地不同；
2018 至 2022 年的很多历史行 OPDATE 为 2026-03-04/05。**未判定哪一边对。** golden 只证明差异来自输入，不证明 wx2 有错。

## 理由

- 与 `tr_umr` v2 保持同一原则，不在迁移时改口径。
- 本地镜像跟随 Wind（[源镜像 ADR](2026-11-17-src-mirror-follows-source.md)），wx2 是旧快照。
- 不可复现时段覆盖面大，逐日追查成本高，且与迁移因子的目的无关。

## 被否方案

- 复现旧 pandas 的跳过缺失：会让缺失当 0 或缩短窗口，违反 §7.5。
- 以 wx2 为准：要改变输入源，需负责人裁定。
- 在 golden 中为 2022-06 等时段加例外：未经确认的类别不进基线。
- 保留 2021-11-15、2022-09-15、2022-12-15 为 golden：这三天仍有少量未解释项，不加例外则不能通过。

## 代价

- 严格口径下，窗口有缺失的股票不产值。golden 四天每因子的已裁定为 12 至 131 只。
- 不可复现时段没有 wx2 对拍，只能靠单测和 golden 四天。
- 残留未解释项：2022-09-15 的 689009.SH，wx2 因子表无行，输入与本地一致；000717.SZ 的 actlargemedcut 因 wx2 复权价只保留
  2 位小数而不同。这两类不进 golden。

## 推论

- 本批次不运行 lake 物化，不写 PG。
- 待负责人裁定：(1) 严格口径是否接受；(2) 以本地镜像为准是否接受；(3) 不可复现区间是否需要重新物化；
  (4) 前瞻收益 CLI 是否改为逐截面日 all_a。
