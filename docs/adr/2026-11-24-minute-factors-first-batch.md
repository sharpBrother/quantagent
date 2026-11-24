---
title: 第一批四个分钟因子：无定义记缺失、排除日无日值、只在 all_a 内产出
status: active
created: 2026-11-24
updated: 2026-11-24
applies_to:
  - src/quantagent/features/library/minute/
  - src/quantagent/features/panel/minute.py
  - src/quantagent/domain/ports/minute_bar.py
  - tests/integration/test_minute_factors_wx2_live.py
supersedes: null
superseded_by: null
---
# 第一批四个分钟因子：无定义记缺失、排除日无日值、只在 all_a 内产出

## 背景

迁移 Current-20 的 `corr_vrlag`、`real_kurt`、`ratio_realupvar`、`ratio_realdownvar`（旧仓 `factors/factor_min.py`）。
日值用当日 241 根分钟，消费值为最近 5 个开市日日值的均值乘以 -1。本地分钟数据从 2024-07-30 起；
2022-01 至 2024-07 没有源数据，负责人 2026-11-24 决定不迁移 wx2 旧值。

## 决策

负责人 2026-11-22、11-24 裁定：

1. **无定义记缺失，不写 0。** 上涨（下跌）分钟不超过 1 根时，`ratio_realupvar`（`ratio_realdownvar`）不产日值，旧代码写 0。
   `real_kurt` 在 pandas 判为零方差时不产日值，旧代码经 pandas 返回 0。判定与 pandas 2.3.3 `nanops.nankurt` 相同：
   分母 `(n-2)(n-3)·m2²` 经 `_zero_out_fperr`（`|x| < 1e-14` 置零）后为 0。
2. **排除日无日值。** 分钟分区登记的排除股票在当日不产日值，不进五日均值，物化不中断。
   为此 `MinuteBarRepository` 新增 `excluded_codes(as_of, day)`，只增不改。
3. **产出范围为截面日 `all_a`。** 旧代码丢弃流通市值缺失的股票日；`all_a` 要求两个市值字段都有值，所以范围内等价，不新增市值端口。
4. 其余计算细节照旧复现：同日内相邻分钟收益（每日 240 个）、零成交 bar 保留、pandas 的 Fisher 偏差修正峰度、
   成对剔除缺失的相关系数、五日均值跳过缺失且没有最少样本数。

## 理由

无定义的值写 0 会被当作真实观测进入均值与截面排序（AGENTS.md §7.5）。排除日的数据已被判定为不可信，不能参与计算。

## 被否方案

- **real_kurt 用真实峰度**：这类股票当日只有 ±1e-6 量级的两根非零收益，峰度数值很大但不反映真实波动。
- **排除日让整段读取报错**：一个股票日的问题会让全市场物化中断。

## 代价

- 与 wx2 对拍只能用 2025-09-24 之后的日期。抽样显示 2024-08-01 至 2025-08-14 旧表 ratio 一致率约 7%，
  corr 与 kurt 在 2025-03 至 2025-06 也有大面积不一致，2025-09-24 起全部一致。未判定哪一边对，未追查。
- golden 共 9 个截面日（含 2026-01-26 至 01-30 排除窗口），逐日列式 fixture 合计约 2.6MB。
- 五日均值没有最少样本数，沿用旧行为；窗口内只剩一天有值也会产出。
