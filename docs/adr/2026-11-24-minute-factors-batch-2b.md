---
title: 第二批分钟因子：pxret21 截面中性化、排序的堆排序兜底、golden 截面日按修正日排除
status: active
created: 2026-11-24
updated: 2026-11-24
applies_to:
  - src/quantagent/features/library/minute/batch_2b.py
  - src/quantagent/features/library/cross_section.py
  - src/quantagent/features/library/_legacy_sort.py
  - src/quantagent/features/panel/minute_2b.py
  - src/quantagent/cli/minute_factors_2b_materialize.py
  - tests/integration/test_minute_factors_2b_wx2_live.py
  - tests/golden/market_data/minute_factors_2b/
supersedes: null
superseded_by: null
---
# 第二批分钟因子：pxret21 截面中性化、排序的堆排序兜底、golden 截面日按修正日排除

> 中性化路径与存残差由负责人 2026-11-24 裁定（只适用于带 `_neut_pxret21` 后缀的 core_up、core_down）；其余为调度方建议，延续既有缺失原则。

## 背景

Current-20 第二批的三个分钟因子（旧仓 `factors/factor_min.py` 637-687 行，别名见
`alpha_factory/performance_factor_single.py` 36-39 行）：

- `pf_single_corr_vrlaglarge_5_mean_neg`：按分钟成交量降序取前 `round(tlen/3)` 根，算成交量与前一根收益的相关，五日均值，方向 -1。
- `pf_single_core_up_20_mean_pos_neut_pxret21`、`pf_single_core_down_20_mean_neg_neut_pxret21`：上涨（下跌）分钟收益的加权和除以范数，二十日均值，再对 pxret21 做截面中性化。

wx2 的 `stock_corr_vrlaglarge`、`stock_core_up`、`stock_core_down` 只存未中性化的日值，`numeric(10,6)`。中性化在消费端做，wx2 没有中性化后的参考值。

## 决策

1. **身份。** `feature_id` 用登记 id，即带 `_neut_pxret21` 后缀的那个（`registered_factors.json` 与 `REGISTERED_VARIANT_FACTOR_IDS` 一致）。`definition_version = "v1"`。`param_hash` 包含窗口、聚合、方向、日值名和中性化口径。
2. **pxret21 的定义。** 数据源是日行情的 `adj_close`（即 `ASHAREEODPRICES.S_DQ_ADJCLOSE`）。窗口取截至事件日的 21 个开市日价格点，即 20 个区间。`pxret21(d) = (P(d) − P(d₋₂₀)) / |P(d₋₂₀)|`，任一端缺失或基准价为 0 时缺失。出处：`refresh_performance_factor_fast_ic.py` 第 2030-2060 行（paired endpoints）。
3. **中性化。** 每个事件日一个截面回归。y 为窗口均值乘方向（+1 或 −1），再做 MAD 去极值（中位数 ± 3·MAD，MAD 为 0 时不裁剪）。x 为 pxret21，做工具去极值（中位数 ± 3·MAD，MAD 为 0 时裁成中位数）。OLS 带截距，样本为 y 与 x 都有值的股票。输出值为残差 `neutral_value`，不做 z-score。数值实现与 `alpha_factory/preprocessing.py:114-143` 的 statsmodels OLS 一致。
4. **有效样本少于 20 时抛错。** 旧代码（`neutralize` 默认 `min_obs=20`）在样本不足时返回未中性化的 y。这是回退，按 §7.7 不复现，改为抛错、不产出该截面日。
5. **排序的并列顺序。** 相关的 top-third 复用 `_legacy_sort.legacy_descending_order`（pandas `nargsort` 降序路径，`sorting.py:436-441`）。移植补上了 numpy quicksort 递归深度超限后的堆排序兜底（`aheapsort_` 逐行移植）。旧移植在这里抛错，属于「不给对不上旧仓的顺序」的既定做法，但这次真实数据确实会触发，所以必须实现。
6. **血缘。** `knowledge_dt` 与 `pit_grade` 由 `derive_feature_lineage` 推导。中性化因子的输入是窗口内 20 个分钟日、基准日与事件日两个价格端点。两类输入都是 `same_day_close`、等级 A，所以结果为事件日、A 级。
7. **golden 截面日。** 2025-09-24 之后，避开 `docs/adr` 记录的分钟修正日及其后 20 个开市日（共 46 个修正日，最早 2025-10-17，最晚 2026-11-18）。按这条规则，2025-09-24 之后的可用截面日只有 2025-09-24 至 09-30、2025-10-09 至 10-16 和 2026-03-02 至 03-25（2026-02-23 至 02-27 与 2026-06-01 也因为 01-22 与 04-30 的修正日及其后 20 个开市日被排除）。日值比对用 2025-09-24、2025-10-15 和 2026-03-02。2026-03-02 的 20 日窗口（2026-01-26 至 03-02）含 2026-01-26、01-27、01-29、01-30、02-03 五个排除日，且窗口内没有修正日。
8. **物化入口。** 新子命令 `lake materialize minute-factors-2b --feature <id> ...`，与第一批的 `minute-factors` 并列，不改第一批行为。股票范围复用 `cli/_universe.py` 的 `all_a_members_by_day`。

## 负责人裁定（2026-11-24）
- 中性化采用 `refresh_performance_factor_fast_ic` 路径（IC 检验与准入所用）：y 用 MAD 去极值、样本下限 20、pxret21 两端价格配对。
  复合评分路径 `performance_factor_score.py:328-332`（工具去极值、`min_obs=2`、首末有值日）不采用。
- 长表存残差，不存 z-score。同一截面两者只差一个正的倍数，排序与 IC 不变；z-score 属于打分层。
- 有效样本少于 20 时不产出该截面日（第 4 条）。
## 理由

- 中性化与去极值的每一步都对应旧仓代码行，并用 wx2 输入复现。残差在 10204 个 (因子, 股票) 对上全部一致，最大差 2.5e-7，输入的 6 位小数舍入可以解释。
- 堆排序兜底：真实数据 2026-02-27 的 300820.SZ 成交量（240 个元素）触发 numpy quicksort 的深度上限，兜底的一段长 9、含并列。不移植就无法得到该股票的 top-third。移植后与 pandas 2.3.3 一致。

## 被否方案

- **用 wx2 的日值直接当中性化输入。** 会把旧表的 6 位小数舍入带进残差，并与本地数据来源耦合。本次只在 golden 测试里用 wx2 做参考，生产路径全部走本地。
- **排除日的 20 日均值补 0。** 违反 §7.5。排除股票当日无值，均值只在有值日上平均。
- **直接调用 `np.argsort(kind="heapsort")` 做兜底。** 与 quicksort 内部的堆排序在并列位置上不一致（见代价）。

## 代价

- **堆排序的并列顺序只有 pandas 对拍。** 直接的 `np.argsort(kind="heapsort")` 在并列位置上与本移植不同（无并列时一致）。quicksort 内部的堆段与公开的 heapsort 可能是两份实现，本次以 pandas quicksort 为准。依据：真实段（长 9，5 个不同值）与 101,779 个真实 240 元素数组的 pandas 对拍全部一致；调度方另用中位数取三退化序列、锯齿与少值并列数组构造 30,283 个数组，其中 2,556 个触发兜底，`legacy_quicksort_order` 与本机 `np.argsort(kind="quicksort")` 逐下标全部一致。
- **golden 只覆盖日值与事件日的中性化。** 2025-10-15 与 2025-09-24 只做日值比对，中性化只在 2026-03-02 做。wx2 没有中性化参考值，中性化结果是「wx2 输入 + 同一纯函数」的一致性检查，不是对旧消费端的落库比对。
- **排除日在日值层没有已裁定项。** 三个日值截面都不是排除日。排除的影响体现在 20 日均值与残差里：2026-03-02 窗口内 wx2 有值的排除样本为 259 个（股票, 日）对，逐行扣除后残差全部一致。
- **fixture 体积 6.0MB。** 22 个截面日文件，每个 278KB 左右，最大的 2026-03-02 为 459KB（含 `pxret21`），均低于 512KB。

## 验证结果

- `tests/integration/test_minute_factors_2b_wx2_live.py`：4 个用例全部通过，耗时约 2 分 40 秒。
  - 日值：2025-09-24（5072 只）、2025-10-15（5074 只）、2026-03-02（5102 只）三个截面、三个因子，一致 / 已裁定 / 其他 = 全部一致 / 0 / 0。
  - pxret21：本地与 wx2 逐股票对拍，5102 只，最大差在 1e-9 以内，不一致 0。
  - corr 五日均值（2026-03-02）：5102 只，一致 5102，其他 0。
  - 中性化残差（2026-03-02）：10204 个 (因子, 股票)，一致 10204，其他 0，最大差 2.5e-7，容差 1e-5。
- 单元测试：分钟日值与 pandas 旧写法逐日对拍、截面去极值与 statsmodels 对拍、面板接线（排除日、血缘、残差和为零）、堆排序兜底的真实段回归。
