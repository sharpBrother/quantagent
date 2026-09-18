---
title: PIT 规则体系
status: active
created: 2026-09-16
updated: 2026-09-18
applies_to:
  - src/quantagent/contracts/visibility/
  - src/quantagent/domain/pit/
  - src/quantagent/features/
  - src/quantagent/publish/
  - docs/migration/wx2-table-list.yaml
---

# PIT 规则体系

前置阅读：[temporal-semantics.md](temporal-semantics.md)（三条时间轴与四种
时间形态）。本文讲可见性规则本身。

## 核心命题：每个数据集的 PIT 规则都不同

来源发布时间不一定就是可见日，系统采集时间更不是。举四个例子说明规则为何
必须逐数据集声明：

| 数据集 | 可见日的实际规则 |
|---|---|
| 交易所日行情 | 收盘后当日即公开 |
| 上市公司财报 | 以公告日为准；缺公告日则该行不可见 |
| 国家统计局 CPI | 按官方发布日历，每月固定日期 |
| 卖方一致预期 | 供应商的数据更新有自身节奏，与个股公告无固定关系 |

四条规则的形式完全不同，不可能用一个通用公式覆盖。因此规则必须是**声明式
的、可测试的、可被引用的**一等公民。

## 哪些对象不配 visibility

visibility 管的是**观测何时可知**。下列对象不是观测，**不写 visibility
YAML**，也**不得作为 PIT 查询的数据集**（fail-closed 仍然成立：没有规则
就不能当研究序列读）。只允许做身份/代码 join：

- 系统代码表（如聚源 `CT_SystemConst`）
- 证券/指数/期货主数据（如 `SecuMain`、`ASHAREDESCRIPTION`）
- 指标目录（如 `C_ED_IndicatorMain`，时间序列在数据表里）
- 行业/代码对照（如 `tushare_ths_industry_mapping_citics`）
- 手维护对照与配置映射（如 `mapping_industry_etf`、`strategy_citics_list`）
- 当前名册、暂无进出历史（如旧 `strategy_etf_list*`，类似 `ASHAREDESCRIPTION`）

有纳入/剔除日的**成分与行业归属**（`AINDEXMEMBERS*`、`ASHARESECNINDUSTRIESCLASS`）
是时间序列，要配 PIT。读取延续旧仓：`S_CON_INDATE <= as_of` 且
`(S_CON_OUTDATE IS NULL OR S_CON_OUTDATE >= as_of)`。行情、财报、一致预期
同样要配。`strategy_etf_list*` 暂时不配 PIT、不得当 PIT 数据集读；命名仍
`universe_etf_*`，不按名单再建物理表。

逐表标记见 [../migration/wx2-table-list.md](../migration/wx2-table-list.md)
的 `pit_required`。

## 规则从哪来

新仓不重新发明可见日。以旧仓 `pycharm_workspace` 现役下游为准：公共
`latest_visible_by_key`（`visible_col <= as_of`），以及各研究线 gateway
里对具体表的日期过滤。多处一致则直接写 YAML；缺证据、冲突、或旧码与
已确认新口径矛盾时再问。

已从旧仓钉死、写契约时直接用：

| 家族 | 旧仓过滤 | 新规则 |
|---|---|---|
| 交易所日频（价 / 衍生 / 指数 / 行业指数 / 资金流 / 两融汇总） | `TRADE_DT` 点查或闭区间，调用方保证 `end<=as_of` | `same_day_close`，`event_field=TRADE_DT`，grade A |
| 国债指数 / 黄金现货 | `TradingDay` / `TradeDate` 闭区间 | 同上，`same_day_close` |
| 朝阳一致预期 `con_forecast_stk*` / `der_diver_stk` | `con_date` 落在查询区间 | `source_field` `field=con_date` |
| 盈利预测调整 `rpt_earnings_adjust` | `current_create_date` | `source_field` `field=current_create_date` |
| 业绩预告/快报/朝阳利润 `fin_*` | `declare_date` | `source_field` `field=declare_date` |
| Wind 预告 `ASHAREPROFITNOTICE` | `S_PROFITNOTICE_DATE` | `source_field` `field=S_PROFITNOTICE_DATE` |
| 聚源宏观（除货币供应） | `InfoPublDate <= as_of`；空发布日不可见；同指标同期取最晚发布 | `source_field` `field=InfoPublDate` |
| 货币供应 `ED_MoneySupply` | **不用** `InfoPublDate`，可见日 = `EndDate` 次月 15 日 | `fixed_lag` 或等价推导，grade B |
| 中长期贷款余额空发布日 | 次月 20 日 | 仅该指标；其余 JY 空发布日仍不可见 |
| Tushare `shibor` / `us_treasury_yield` | `trade_date <= as_of` | `same_day_close`，`event_field=trade_date` |
| Tushare `eco_cal` | `event_date <= as_of` | `source_field` `field=event_date` |
| 金十 ISM | `publish_date < as_of`（不含当日） | `source_field` 或需严格小于；与 CPI/PPI 不同 |
| 金十中国 CPI/PPI | 公布日对齐交易日，**含当日** | 与 ISM 分数据集，不要合成一条规则 |
| FRED / GPR | vintage 严格 `< as_of`，禁止用观测日当可见日 | `source_field` 首次 vintage |
| `FIN_APPO_RELE_DATE` | `DECLARE_DATE < as_of` | `source_field` `field=DECLARE_DATE`，不含当日 |
| `fund_share` | `trade_date` 区间，MDS **不**前值填充 | `same_day_close`；禁止 ffill |
| 指数 / 行业成分 `AINDEXMEMBERS*` | `S_CON_INDATE <= as_of` 且 `(OUTDATE IS NULL OR OUTDATE >= as_of)` | 区间命中，闭区间；源表无公告日，`knowledge_dt = valid_from = INDATE` |
| 指数 / 行业成分 `AINDEXMEMBERS*` | `S_CON_INDATE <= as_of` 且 `(OUTDATE IS NULL OR OUTDATE >= as_of)` | 区间命中，闭区间；源表无公告日，`knowledge_dt = valid_from = INDATE` |
| 当前名册 `strategy_etf_list*` | 无历史进出，类似 `ASHAREDESCRIPTION` | **不配 PIT**，不得当 PIT 数据集读 |

公共 PIT 原语只保证 `visible_col <= as_of`；具体列由调用方传入。`latest_visible_by_key` 在旧仓生产路径上**未接线**。

调用方把 `as_of` 设成 T−1（优化器市值、raw 日历）不是数据集规则，YAML 仍按源表可见日写，T−1 留给研究读取的 `as_of`。

### 待裁定（旧仓互相冲突，未写 YAML）

1. **财报 `ANN_DT` 当日是否可见**：`agent_style_rotation` 用 `<= as_of`；`raw_loader` 用 `< adj`。列和「空公告不可见、同报告期留最后一次」已钉死，只差不等式。
2. **`der_prob_excess_stock`**：`(declare_date < adj) OR (entrytime < adj)`，比双字段都可见更松。
3. **成长事件 `confirm_date`**：ETF 路径 `<= T`；成长策略 / universe 用调仓日前第 2 个交易日。

金十 ISM 的 `< T` 与 CPI/PPI 的含当日已按数据集分开，不再问。WGC 旧文档自认非严格 PIT，迁入前单独标 grade。

## 规则文件

放 `src/quantagent/contracts/visibility/`，与代码一同版本化，一个数据集
一个文件。

### same_day_close

点事件在业务日收盘后可见。求解为 ``event_field`` 的日期 ``<= as_of``：
``as_of`` 当天可见，更晚的业务日不可见。已实现。

```yaml
# equity_eod.yaml
dataset: mart.equity_eod
temporal_kind: point_event
event_field: trade_dt
visibility:
  rule: same_day_close        # 收盘后可见
  grade: A
  rationale: 交易所收盘行情当日盘后即公开
```

### source_field 加 fallback

截止列是 ``visibility.field``（不是 ``event_field``），该列日期 ``<= as_of``。
``as_of`` 当天可见，更晚不可见。主规则已实现；``fallback`` 尚未实现，查询
路径遇到必须 fail-closed。``feature.value`` 的 field 是 ``knowledge_dt``：
因子截面日可以早于可见日，把 ``event_dt`` 当可见日会引入前视。

```yaml
# fin_statement.yaml
dataset: mart.fin_statement
temporal_kind: period_with_revision
period_fields: [report_period_end, statement_type]
visibility:
  rule: source_field
  field: ann_dt               # 以公告日为准
  grade: A
  fallback:
    rule: statutory_deadline  # 缺公告日时按法定最迟披露日推断
    grade: B
```

`fallback` 的 `grade` 必须不高于主规则——推断出来的可见日不可能比原生
字段更可信。

### release_calendar

```yaml
# macro_cpi.yaml
dataset: mart.macro_cpi
temporal_kind: period_with_revision
visibility:
  rule: release_calendar
  calendar: cn_nbs_release
  grade: A
```

发布日历本身是一份数据，放 `db/seeds/` 并有自己的维护流程。

### 内置规则类型

| 规则 | 语义 | 典型等级 |
|---|---|---|
| `same_day_close` | 业务日收盘后可见 | A |
| `source_field` | 以源端某个原生日期字段为准 | A |
| `release_calendar` | 按官方发布日历 | A |
| `statutory_deadline` | 按法定最迟披露日推断 | B |
| `fixed_lag` | 业务日 + N 个交易日或自然日 | B / C |
| `ingest_time` | 以系统采集时间为准（兜底） | C / D |

本切片已实现 `same_day_close` 与 `source_field`。其余规则
（`release_calendar` / `statutory_deadline` / `fixed_lag` / `ingest_time`）
在查询路径上遇到必须 fail-closed，避免半套求解被当成已支持。

`ingest_time` **仅对系统上线后采集的数据有效**。对一次性迁入的存量数据，
它的 `_ingested_at` 全部等于迁移日，此时必须配合 `pit_recoverable: false`
与 `pit_from`，否则等于伪造历史。

### 每条规则强制带 grade 与 rationale

`rationale` 是必填的自然语言说明。它的作用是让规则可被审查——三个月后
看到 `grade: B` 时，能知道为什么是 B 而不是 A。

## 等级分级标准

| 等级 | 标准 | 含义 |
|---|---|---|
| A | 可见日来自源端原生的发布时间或官方发布日历 | 时间戳属于市场 |
| B | 可见日由制度性规则推断（法定披露期限、固定延迟） | 时间戳可靠但非市场原始 |
| C | 可见日由采集时间近似，且采集是持续进行的 | 时间戳属于本系统，保守但粗糙 |
| D | 可见日不可信——存量一次性迁入、历史版本已丢失、或来源不明 | 不能用于严肃的 PIT 回测 |

关键区分是**时间戳的归属**：A 级的时间戳属于市场，B 级属于制度推断，
C/D 级属于系统动作。没有源拉取 vintage，不能把「本系统何时首次看到」写成
B 级。

B 级用作 PIT 是**保守**的：法定最迟日或固定延迟不早于真实发布时间，所以
可能少用一些本可用的信息，不会引入未来信息。这一点让 B 级在实践中可用。

D 级的问题不是保守也不是激进，是**不可估计**——无法判断它引入了多少未来
信息。

## 规则缺失是唯一 fail-closed 的情形

**没有可见性规则的数据集不允许参与任何 PIT 查询。**

这是全系统唯一的硬阻断。理由：一个数据集如果连"什么时候能知道"都没定义，
任何用它做的时间序列研究都不成立，而这种不成立无法通过展示更多信息来
补救。

`tests/contracts/` 校验：每个 lake 数据集是否都有对应的 visibility 规则。
缺失即 CI 失败。

相比之下，**低等级不阻断**——见下面第五节。

## 因子层的强制字段

因子**不带** `published_at` / `ingested_at`（那是源层概念，因子没有
"发布"这件事），但必须带下列字段，缺一不可：

| 字段 | 含义 | 填法 |
|---|---|---|
| `event_dt` | 因子截面日 | 计算输入 |
| `asset_id` / `feature_id` / `definition_version` / `param_hash` | 身份 | 计算输入 |
| `value` | 因子值 | 计算输出 |
| `knowledge_dt` | 因子可见日 | **自动派生** |
| `pit_grade` | PIT 可信等级 | **自动继承** |
| `computed_at` / `run_id` | 可复现身份 | 运行时写入 |

### knowledge_dt 的推导

```
knowledge_dt = max(所有输入的 knowledge_dt) + 因子自身声明的计算延迟
```

因子可以声明**更严格**的规则（更晚可见），但**不允许更宽松**。写入函数
校验这一条。

"更严格允许、更宽松禁止"的理由：更严格只会少用信息，是保守方向；更宽松
会引入未来信息，是错误方向。允许保守方向的调整，是因为有真实场景——例如
某个因子虽然输入都在 T 日可见，但实际计算要等隔夜批处理完成。

### pit_grade 的继承

沿依赖图取**最差值**（木桶原理），不可手工抬升。

```
pit_grade = min(所有输入的 pit_grade)     # 按 A > B > C > D 排序
```

### 为什么必须自动推导

如果这两个字段可以人工填写，那么"一个 D 级输入产出的因子被标成 A 级"只
需要一次疏忽，而且这个错误不会报错、不会崩溃，只会让一批研究结论悄悄
失效。

实现上，因子写入函数**拒绝接受调用方传入的这两个字段值**——不是覆盖，是
报错。这样错误在写入时暴露，而不是在使用时。

### as_of 是必填的

所有因子计算读取上游时强制传 `as_of`，**不允许无 `as_of` 的读取路径
存在**。

这是接口层面的约束，不是纪律要求。只要提供一条不传 `as_of` 的便捷路径，
它就一定会被用在需要 PIT 的地方。见
[../architecture/ports-and-adapters.md](../architecture/ports-and-adapters.md)。

## 不可恢复的显式标记

契约中两个字段用于如实记录历史缺口：

| 字段 | 含义 |
|---|---|
| `pit_recoverable` | 该数据集的历史修订史是否可恢复 |
| `pit_from` | PIT 可信起算日。此日之前的可见日不可信 |

示例：

```yaml
# wx2 存量迁入的数据集
dataset: mart.legacy_factor_score
temporal_kind: point_event
event_field: event_dt
visibility:
  rule: ingest_time
  grade: D
  rationale: wx2 存量一次性迁入，源端修订史已丢失，采集时间全部等于迁移日
pit_recoverable: false
pit_from: 2026-10-01           # 迁移日；此日之前的 knowledge_dt 不可信
origin: wx2
recomputable: false
```

## 声明式管控而非硬阻断

低等级数据**允许**进入回测与信号层。但回测、信号、发布产物的 schema 强制
携带 `pit_report` 字段。

### pit_report 字段

| 字段 | 内容 |
|---|---|
| `inputs` | 每个输入数据集的 `dataset`、`grade`、`pit_from`、`pit_recoverable` |
| `worst_grade` | 所有输入中的最差等级 |
| `untrusted_ratio` | 回测区间中落在 `pit_from` 之前的样本占比 |
| `untrusted_range` | 不可信区间的起止日期 |
| `notes` | 各输入的 `rationale` 汇总 |

### 为什么选声明式

硬阻断（低等级数据不允许进回测）的问题是：它会让整个存量历史都不可用，
而存量历史是唯一的长样本。结果不是"研究更严谨"，而是"绕过阻断"或"不做
长样本研究"。

声明式的前提是**信息不得被隐藏**：

- 回测结果必带 `pit_report`
- 发布层**强制展示** `pit_report`，不允许只展示数值
- 前端不得把 PIT 等级折叠进"更多信息"

是否采信由人判断，但判断所需的信息必须在眼前。

这个设计只在最后一环成立时才有效——如果发布层可以隐藏 PIT 信息，声明式
就退化成"没有管控"。因此发布层的强制展示是 `tests/contracts/` 校验的项目。

## 规则变更流程

可见性规则的变更会改变所有历史 `knowledge_dt`，因此比普通代码变更更重：

1. 变更前：跑一次全量影响评估——有多少数据集、多少因子、多少已发布结论
   的 `knowledge_dt` 会变
2. 在 `docs/adr/` 记一份，说明变更原因与影响范围
3. 变更后：受影响的因子必须重算，不允许新旧规则的结果混存
4. 已发布的结论若受影响，在发布产物里标注"因规则修订而重算"

第三条是硬要求：同一份因子长表里混着两种规则算出的 `knowledge_dt`，会让
任何 PIT 查询的结果无法解释。

## 常见错误清单

供 code review 时对照：

1. 数据集没有 visibility 规则就接入了研究链路
2. `fallback` 的 grade 高于主规则
3. 因子的 `knowledge_dt` 是人工填写的
4. 因子声明了比推导结果**更宽松**的可见日
5. `pit_grade` 被手工抬升
6. 存量迁入数据用了 `ingest_time` 但没设 `pit_recoverable: false`
7. 存量迁入数据没设 `pit_from`
8. 回测结果没有 `pit_report`
9. 发布产物有 `pit_report` 但前端不展示
10. 规则变更后没有重算受影响的因子
11. 读取接口提供了不传 `as_of` 的路径
12. 不同来源的同类数据用了同一条规则，但其实发布节奏不同
