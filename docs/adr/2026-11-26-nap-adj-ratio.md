---
title: nap_adj_ratio 迁移口径——entrytime 截止消除前视、对齐新仓域、并列年度复现
status: active
created: 2026-11-26
updated: 2026-11-26
applies_to:
  - src/quantagent/features/library/fundamental/nap_adj_ratio.py
  - src/quantagent/features/panel/nap_adj_ratio.py
  - src/quantagent/adapters/postgres/suntime_adjust.py
  - src/quantagent/contracts/visibility/src.suntime.rpt_earnings_adjust.yaml
  - tests/golden/test_nap_adj_ratio_wx2.py
supersedes: null
superseded_by: null
---
# nap_adj_ratio 迁移口径

## 背景

`nap_adj_ratio`（朝阳永续盈利预测上调幅度中位数，`pf_single_nap_adj_ratio_1_mean_pos`，方向 +1）
迁移自旧仓 `factors/factor_rpt.py` 的 `NAP_ADJ_RATIO`。输入是 `src_suntime.rpt_earnings_adjust`
（分析师对盈利预测的调整记录）。与 did_ratio 等已迁移因子相比，它有三个独有的口径问题，
需要逐条裁定。

## 决策

### 1. 可见性截止用 entrytime，业务窗口用 current_create_date，两者分离（2026-11-26 裁定）

源表有两个时间字段：`current_create_date`（研报的研报日期，事件时间）与 `entrytime`
（供应商入库时间，真实可见时间）。旧仓只用 `current_create_date` 做 30 天窗口
`[ob_date − 30, ob_date]`，**没有 entrytime 截止**——这是前视：研报日期落在窗口内但
尚未入库的记录也被算进去了。

裁定（负责人，2026-11-26）：

- **业务窗口**仍按 `current_create_date ∈ [观察日 − 30 天, 观察日]`（含两端，自然日）。
- **可见性截止**单独用 `entrytime ≤ 观察日`。
- 两者是**正交的两步裁剪**，不是把窗口搬到 entrytime 上。

实测前视证据（wx2，300750.SZ，观察日 2024-05-06）：旧口径纳入 105 行，新口径 101 行——
多看的 4 行是 `current_create_date` 为 05-05/05-06 但 `entrytime` 为 05-07 的研报，
观察日当天根本看不到。entrytime 截止正确消除了这部分前视。可见性契约 grade A
（entrytime 是供应商首次入库时间，真实可见字段），`pit_recoverable: true`。

### 2. 域与日频对齐新仓，刻意偏离旧仓（2026-11-26 裁定）

- 旧仓：逐**自然日**（周日也产值）、覆盖全部有研报的股票、`stock_code not like '2%'`
  粗糙剔除深 B。
- 新仓：逐**交易日**、域为当日 all_a 成员去掉当日 ST（与 cutamp/mif/did_ratio 一致）。

对齐的后果：不能与 wx2 旧值逐行直拍。golden 改用 **wx2 源输入经新仓同一算法重算比对**，
验证"同输入同输出"，差异单独登记。B 股 / 基金代码不在 all_a 域内被天然剔除，不再需要
旧仓的 `not like '2%'` 显式过滤（该规则把 `92xxxx` 北交所误归为 BJ 的问题也随之消失——
号段映射只做 `6/5→SH、9→BJ、其余→SZ` 的反查回填）。

### 3. 并列年度与中没有 pandas，逐行复现

旧仓 `groupby('report_year').count().sort_values(ascending=False).index[0]` 取条数最多的
年度。`sort_values` 并列时的顺序依赖 pandas 内部排序，不能假设"反正就是最小年度"。用
`features/library/_legacy_sort.py` 的 `legacy_descending_order` 逐行复现，300 次随机
年度计数对拍与真实 pandas 零不一致。小样本下等价于"并列取较小年度"。

中位数用 `quantile(0.5)` 线性插值语义：奇数取中位，偶数取中间两值均值（Decimal 精确，
不经过 float）。`report_year` 为空的行不参与分组（pandas groupby 默认行为），
`np_adjust_rate` 为空的行不参与中位数（pandas quantile 跳过 NaN）。

### 4. knowledge_dt 箍到 max(输入最晚 entrytime, event_dt)（2026-11-26 裁定）

`knowledge_dt` 语义与其他因子一致：**"该截面值最早何时可见/可用"**。截面在 event_dt 才
形成可见（窗口右端点就是 event_dt，当日是否还有新调整入库要到 event_dt 才确定）。

nap_adj_ratio 是第一个稀疏事件输入因子：窗口内最新入库的 entrytime 可能远早于 event_dt
（例：300750.SZ 2024-05-06 最晚可见 entrytime=04-24，早 12 天），导致裸血缘
`max(entrytime) < event_dt`，触发写入校验拒绝。行情因子不会有这个问题——截面日当日
行情本身就是输入，`max(trade_dt)=event_dt` 恒成立。本因子没有当日输入，需在 panel 层
显式箍制：`knowledge_dt = max(max(entrytime), event_dt)`。**这不是手工抬升**（pit_grade
仍取输入最差、不受箍制影响），而是与行情因子同一语义的正确表达。后续 event_sue 等
稀疏事件因子会有同样需求。

### 5. 稀疏因子，缺失不补 0

窗口内无有效调整记录的股票不产值、不落行（AGENTS.md §7.5 缺失就是缺失）。全 all_a 域
单月实际覆盖约 2100 只股票（有研报的），行数远少于 did_ratio 的全覆盖。

## golden 对拍结果

fixture `tests/golden/market_data/nap_adj_ratio/20240515.json`（wx2 `stock_nap_adj_ratio`
旧值横截面，带后缀代码，49KB），golden 测试连本地 PG 读 `src_suntime` 源行经新仓算法重算
比对（模式同 did_ratio：源行不入 fixture；本地 PG 与 wx2 窗口源行数一致已验证=38780）。

20240515 共 2132 只：

- **一致 2070（97.1%）**：重算值 = wx2 旧值，精确一致。
- **消除前视 62（2.9%）**：entrytime 截止剔除了影响结果的源行，重算值与旧值不同，
  是决策 1 的刻意偏离。抽查确认差异方向正确（002518.SZ 窗口 18 行剔除 3 行未入库研报，
  中位数 −0.0718→−0.0359）。
- **其他 0**：零无法解释的差异。

## 物化与日更

- 全历史回填：2018-01 至 2026-10，106 个月连续，2,237,020 行，pit_grade 全 A，
  knowledge_dt 违规 0。单一 as_of=2026-11-26 读取，per-row knowledge_dt 由 entrytime
  血缘推导。as_of 宽窄不影响结果（迟入库行 entrytime>观察日必然被窗口裁剪排除）。
- 04:10 日更：接入 `feature_daily_main`。就绪输入仅 `ashareeodderivativeindicator`
  （all_a 成员由它决定）；`src_suntime_rpt_earnings_adjust` 作为血缘 deps（在采集之后跑）
  但不参与行数就绪判定——与 did_ratio 财报同一处理。
