---
title: DTC / ShortInterest 实施计划
status: active
created: 2026-11-05
updated: 2026-11-05
applies_to:
  - src/quantagent/features/
  - src/quantagent/ingest/
  - src/quantagent/strategy/backtest/
  - src/quantagent/contracts/visibility/
  - src/quantagent/domain/ports/
  - db/migrations/src/0003_wind.sql
  - docs/research/
supersedes: null
superseded_by: null
---

# DTC / ShortInterest 实施计划

内部研究稿（因子 #19，2026-11-05）的落地计划。**只写计划，本文件不改计算代码。**
稿件原文不入库、不对外发布。

正式式分叉（已裁定，写进身份，不得混用）：

- **美股正式表 = DTC**（空头比率 / 日均换手）；裸 SR 只作同族对照。
- **A 股正式表 = SR**（融券余额 / 流通市值）；宇宙 = 两融标的；`DTC_short` 只作对照，预期弱。

同族变体（DTC2–4、SIO、APR 高 SI×低 IO、只改分位/持有期）不另开台账槽位。

---

## 1. 仓库现状（代码事实，不是设计愿望）

`PROJECT.md` 与 `docs/migration/roadmap.md` 仍写：**P3 因子计算未开始，P4 回测内核未开始。**
对照代码：

| 能力 | 实际位置 | 状态 |
|---|---|---|
| 因子声明 / 实现 / 注册 | `src/quantagent/features/{spec,library,panel,registry}/` | 只有职责 docstring，**无 `FeatureSpec`、无库函数、无注册表读写** |
| 因子长表读取 | `FeatureRepository`（`domain/ports/feature.py`）；CLI `quantagent feature {window,cross-section,matrix,metric}` | 已实现 lake / memory；调用方必须传完整 `(feature_id, definition_version, param_hash)` 与 `--as-of` |
| 因子长表写入 | `lake/partitions/write.py` 的 `write_feature_value_parquet` | 布局写入器；**不推导 `knowledge_dt` / `pit_grade`**。`FeatureRepository` 实际是只读 |
| 已实现因子 | `features/library/{price,fundamental,sentiment,macro}/` | **零实现**。测试里只有字面量 `mom_20d` / `turn_20d` |
| NSI / AbTurn / PMO / Amihud / 动量 / DTC / SR | `src/`、`tests/` | **无** |
| 数据端口 | `domain/ports/` 仅 6 个：日历、因子值、因子指标、前瞻收益、分组净值、股票池成员 | 文档里的 `PriceRepository` / `FundamentalRepository` **未落地** |
| 源采集 | `quantagent ingest` | 仅 Tushare `trade_cal`、Wind `ASHAREEODPRICES`。写白名单在 `ingest/writers/tables.py` |
| 两融源表 | `db/migrations/src/0003_wind.sql`：`src_wind.ASHAREMARGINTRADE` / `ASHAREMARGINTRADESUM` | **仅 DDL**。不在 `WIND_PAGED_TABLES`，无 schema/visibility 对，wx2 清单写「本清单不启动迁入」 |
| 股票池 | `UniverseRepository.members_at` | 只读区间成员；**无构造器、无现役 `universe_id`、无两融宇宙** |
| 回测 / 成本 | `strategy/backtest/{contract,vectorized,rebalance,event}/`、`strategy/costs/` | 骨架。`quantagent backtest` **未注册**。`orchestration/` 无 Dagster `Definitions` |
| 成本 / OOS 配置 | 本仓库 | **无**稿件所称 `/workspace/hub/backtests/config.md`。唯一相关合同是 `docs/architecture/backtest-contract.md` 与 ADR `2026-09-19-factor-horizons-and-admission.md` |
| 美股股权源 | Compustat / CRSP / WRDS / `shortint` | **全库零命中**。`src_tushare.us_treasury_yield` 与 FRED 是利率/宏观，不是空头兴趣 |

已接线的 visibility 对只有 8 个：`src.tushare.trade_cal`、`src.wind.ashareeodprices`、`std.trade_calendar`、`mart.universe_member`、`mart.forward_return`、`feature.value`、`feature.metric`、`signal.group_nav`。
没有 visibility 的数据集不得进入任何 PIT 查询。

入口事实：CLI 现有 `calendar / check / db / feature / forward-return / group-nav / ingest / lake / universe`。探索性代码只进 `notebooks/`，禁止新建 `scripts/`。

---

## 2. 因子定义（按稿件，写成本仓库身份）

一个台账槽位，两市场正式式，对照列用不同 `feature_id` 或同一 id 的不同 `param_hash`。
建议身份（实施时再写入 registry，这里先钉语义）：

| `feature_id` | 市场 | 角色 | 公式 | 方向 |
|---|---|---|---|---|
| `sr` | A 股 | **正式表** | \(\mathrm{SR}=\) `S_MARGIN_SECLENDINGBALANCE` / `S_DQ_MV` | 越高越看空 |
| `dtc_short` | A 股 | 同族对照（预期弱） | `sr` / 当月日均换手 | 越高越看空 |
| `dtc_long` | A 股 | 卫星，不另开台账 | 融资余额 / 日均换手 | 越高越看多 |
| `dtc` | 美股 | **正式表** | \((\texttt{shortint}/\texttt{shrout})\) / 同月日均换手 | 越高越看空 |
| `sr_us` | 美股 | 同族对照 | `shortint / shrout` | 越高越看空 |

A 股稳健性列（不换 `feature_id`）：`融券余量 × 收盘 / 流通市值`，用 `param_hash` 区分。
窗口 / 去极值 / 中性化一律进 `param_hash`（规范化 JSON + `digest_json`），不改 `feature_id`。
算法改了才升 `definition_version`。

### 2.1 时点（无前视）

| 项 | 处理 |
|---|---|
| 频率 | 月度调仓 |
| A 股计算时点 | 两融是交易所日频。信号用 `signal_dt` 当日或之前最后一条已可见 `TRADE_DT`。家族规则已裁定：`same_day_close`、`event_field=TRADE_DT`、grade A（`docs/domain/pit-rules.md`） |
| 美股计算时点 | 只用已公布 mid-month SI；双周约 4 日滞后必须写进 `FeatureSpec` 的计算延迟，`knowledge_dt` 只允许更严。禁止用月末尚未公布的 SI |
| 缺失 | 无 SI / 换手为 0 → **不落行**。禁止把旧 SI 前填充成「无空头」 |
| `knowledge_dt` / `pit_grade` | 写入函数自动推导，拒绝手填。A 股输入若都是 grade A 日频，输出默认 A，再叠加声明延迟 |

### 2.2 股票池与过滤

**A 股**

- 宇宙：两融标的（时变）。调入次月纳入、调出当月剔除。
- 剔除：非两融、无融券观测、停牌不可成交；ST/*ST 作敏感性（`ASHAREST` 仅 DDL）。
- 涨跌停 / T+1：评价与回测层声明，不写进因子值。

**美股**

- 宇宙：NYSE/AMEX/Nasdaq 普通股（share code 10/11）。
- 剔除：无 short interest、停牌。稳健性剔 NYSE 市值最低 10–20%、股价 <$5。
- NASDAQ 成交量按 Gao–Ritter 折算后再算换手。

### 2.3 组合与断点

| 项 | 建议规格 |
|---|---|
| 分组 | 每月截面十分位；美股可用 NYSE 断点（`param_hash`） |
| 多空 | 做多最低组、做空最高组。A 股优先 **纯多最低 SR vs 两融宇宙等权 / 中证 800**（融券腿浅） |
| 加权 | 主表等权；附表市值加权 |
| 中性化 | 市值 + 行业残差后再排序为建议规格；未中性化为对照（不同 `param_hash`） |

稿件要求的强制对照（落地评价时至少报这些列，不是另推因子）：

1. DTC 与 SR 单变量十分位 EW/VW，全样本 + 发表后 / 最后 30% OOS
2. vs 换手 / Amihud / 将来的 AbTurn
3. vs 将来的 NSI（存量 ≠ 净发行流量）
4. vs 动量族（Residual Momentum / IND_MOM / PTH；本仓库均未实现）
5. A 股同时报 `dtc_short`（预期弱）与可选 `dtc_long`；扣成本后净收益

本仓库还没有这些对照因子的实现。本轮默认做成**评价时的一次性对照列**，不抢它们的台账槽位。若之后独立落地，对照必须改读同一 `feature_key`，禁止平行口径。

### 2.4 成本与 OOS（对齐本仓库，不发明第二套标准）

稿件引用的 hub `backtests/config.md` **不在本仓库**。落地时对齐已有合同，参数进未来的 `config_digest`：

- 时间语义：`signal_dt` / `decision_dt` / `execution_dt` 分离（`docs/architecture/backtest-contract.md`）。A 股成交价口径必须显式声明（默认建议：信号用已见收盘，执行下一开盘；不得隐含 T+0 收盘对收盘）。
- 股票检验周期：主协议 `oo_5d`，预注册 1D/5D/10D/20D，各绑真实 forward return，不缩放 5D（ADR `2026-09-19-factor-horizons-and-admission.md`）。月度调仓因子仍要报这四个周期，不能只报月频。
- 成本：统一放 `strategy/costs/`（尚未实现）。研究假设写入参数，不另建全局 YAML：A 股单边 10–15 bp + 冲击，空头腿另加融券费；美股单边约 5 bp + 借券费。缺价不前填。
- OOS：全样本最后 30% 预留为默认；美股另报 ConvexPi 发表后切分（2001+）作对照。两者都要完整披露，不事后改主切分。
- 晋级：研究筛选 / Website / 组合三层独立。本计划验收停在**研究筛选**。观点与回测是研究展厅，不授权交易（`researchOnly`）。

在 `strategy/costs/` 与 `vectorized` 内核落地前，评价可以先走 `notebooks/` + 已有 `FeatureRepository` / `ForwardReturnRepository` 读取，结论提炼回本目录；**不**新建 `scripts/`。

---

## 3. 数据依赖与阻塞

### 3.1 A 股（可走，但仍有批准项）

SR 最小字段：

| 用途 | 本仓库已有 | 缺口 |
|---|---|---|
| 融券余额 / 余量 | `ASHAREMARGINTRADE.S_MARGIN_SECLENDINGBALANCE` / `S_MARGIN_SECLENDINGBALANCEVOL` | DDL only；要采集须扩写白名单（`AGENTS.md` §3：改写入目标须问） |
| 流通市值 / 换手 | `ASHAREEODDERIVATIVEINDICATOR.S_DQ_MV` / `S_DQ_TURN` / `S_DQ_FREETURNOVER` | 同上，DDL only，wx2「不启动迁入」 |
| 收盘 / 成交额 | `ASHAREEODPRICES`（已有 ingest + visibility） | 已接线 |
| 两融汇总 | `ASHAREMARGINTRADESUM` | 市场级，**不能**当个股 SR |
| 两融标的进出 | 第一批 `db/src_tables.yaml` **无**专用名单表 | **阻塞口径**：见 §6 Q2 |
| ST | `ASHAREST` | DDL only |
| 停牌 | `ASHARETRADINGSUSPENSION` | DDL only |
| 行业（中性化） | `AINDEXMEMBERSCITICS*` | DDL only；成分切片口径已裁定为 `S_CON_INDATE`/`OUTDATE` 对 `as_of` |

visibility：两融日频属于已裁定家族（`TRADE_DT` + `same_day_close` + grade A）。
**仍禁止无证据顺手写 YAML。** 先反查旧仓 `factors/factor_etf_margin.py`、`data/ETF四象限推送.py`、`core/market_data_service.py`。多处一致再写；冲突或旧码没有 `as_of` 过滤则停下问。wx2 对存量行标了 `pit_recoverable: false`。

不要把 akshare 当默认源：会新增依赖。公开接口最多作 notebook 抽查。

### 3.2 美股（硬阻塞）

DTC 需要 Compustat `shortint`、CRSP `shrout` 与成交量、US 交易日历。本仓库没有这些源、没有 ingest、没有 visibility 证据可反推。
按 `AGENTS.md`，这是**新依赖 + 新持久化 + 无旧仓 as_of 证据**，实施前必须负责人批准。在批准之前，美股只保留公式与对照列设计，不写源 YAML、不采购、不接密钥。

### 3.3 公共工程阻塞（两市场共用）

1. 没有 `FeatureSpec`、没有自动推导 `knowledge_dt` 的写入路径。
2. 没有 `PriceRepository`（以及两融/空头存量的窄端口）。业务层不得新建平行网关。
3. 没有宇宙构造器。
4. 没有 vectorized 分组回测与成本模块。
5. `tests/golden/` 空。路线图要求迁旧因子前先 golden；本因子在旧仓**没有**对等实现，因此 golden 约束是「不要顺手改其他旧口径」，不是「先复现一份旧 DTC」。

---

## 4. 任务与验收（按优先级）

原则：不把整座 P3/P4 工厂为这一个因子建完。只补本因子算得出、验得了所必需的最小路径。
**P0 的裁定没下来，不改写白名单、不加美股源。**

### P0 — 负责人裁定（本计划的入口阻塞）

| ID | 问题 | 验收 |
|---|---|---|
| Q1 | 是否批准把 `ASHAREMARGINTRADE`（及 SR 所需的 `ASHAREEODDERIVATIVEINDICATOR`）列入 ingest 写白名单并启动迁入？wx2 现写「不启动迁入」 | 书面是/否 + 范围 |
| Q2 | 两融宇宙：用「当日融券余额非空」近似，还是另引 Wind 标的名单表（新表）？ | 选定规则；新表必须另批 |
| Q3 | 美股 Compustat/CRSP：本轮挂起，还是批准新源？ | 挂起则美股任务保持文档级；批准才开源契约 |
| Q4 | NSI / AbTurn / 动量对照：评价一次性列，还是先单独立项？ | 默认一次性列 |
| Q5 | 是否允许本因子作为第一个库因子，顺带补最小 `FeatureSpec` + 推导写入？还是等通用 P3 骨架？ | 二选一。推荐「最小写入路径」，不预建 registry UI / Dagster 全家桶 |

### P1 — A 股源与可见性（Q1=是之后）

1. 反查旧仓两融下游，写 `src.wind.asharemargintrade`（及衍生指标，若批准）的 schema + visibility + `docs/contracts/` 一页。`doc_ref` 必须能过 `quantagent check contracts`。
2. 把表加入 `WIND_PAGED_TABLES` 与 `ALLOWED_SRC_WRITE_TARGETS`；沿用 `OPDATE+OBJECT_ID` 游标、insert-only、默认 `write_db=False`。
3. 契约测试：配对、`same_day_close`、缺规则 fail-closed。
4. **验收**：`quantagent check contracts` 绿；无 `--write-db` 不能写；PIT 单测不碰库。此时还不算因子完成。

### P2 — 两融宇宙与读取端口（Q2 裁定后）

1. 物化 `mart.universe_member` 区间行（调入次月 / 调出当月）。`universe_id = digest(规则配置规范化 JSON)`。
2. 窄扩展端口，不要新平行层。优先：`PriceRepository` 的最小切片（收盘、换手、流通市值），外加两融余额读取（若不宜塞进 Price，就新增一个领域 Protocol，签名只含 `as_of` / `asset_id` / `event_dt`）。
3. **验收**：`quantagent universe members --universe-id <两融> --dt --as-of` 只返回当时可融券成员；memory 适配器可单测进出日。

### P3 — 纯函数 + 长表身份（不依赖库已迁完）

建议落点：`src/quantagent/features/library/sentiment/`（现有分域里最接近「持仓密度」；不新建 `short/` 包）。

1. 纯函数：`short_ratio`、`days_to_cover`、截面 Winsor；换手 0 / SI 缺失 → NaN，不 ffill。
2. `FeatureSpec` 最小集：输入依赖、频率、声明延迟、官方市场。`knowledge_dt` 由写入路径推导。
3. 写入 `var/lake/feature/value/`（`asset_class=stock`），旁置 `var/lake/feature/_registry/`。
4. **验收（什么叫因子算完）**：
   - unit：公式、缺失、换手 0、Winsor、A 股正式式是 SR 不是 `dtc_short`
   - contracts：长表 schema；手填 `knowledge_dt` / 抬升 `pit_grade` 被拒
   - 用 memory 仓库能 `scan_cross_section` 读回 `sr` / `dtc_short`
   - 无 SI 的资产不出现在该日截面

### P4 — 评价与强制对照（研究筛选，不是组合准入）

1. 十分位 EW/VW；A 股主结果 = 两融宇宙内 `sr`；必须并列 `dtc_short`。
2. 对照列按 Q4：换手、Amihud（旧仓 `stock_amihud_illiq` **明确不迁**，对照用现算）、NSI、动量——能算则算，缺数据就在报告里写「未算 / 阻塞」，不编造。
3. 预注册 1D/5D/10D/20D + 月度持有；最后 30% OOS；扣研究成本假设后的净收益。
4. 强制带 `pit_report`。
5. **验收**：`docs/research/` 一页结论（覆盖、IC/分组、OOS、对照、成本、失效条件）。不自动进 Website，不授权交易。

### P5 — 美股 DTC（仅 Q3 批准后）

1. 源契约与 visibility（无旧仓证据 → 规则本身必须再裁定）。
2. 正式 `dtc`，对照 `sr_us`；NASDAQ 折算进 `param_hash`。
3. OOS：最后 30% **和** 2001+ 都报。
4. **验收**：与 P3/P4 对称；未批准源之前本段保持阻塞。

港股 / 欧股：本计划范围外。

---

## 5. 预计触碰的文件 / 模块

落地时按任务改，不提前建空文件。

| 阶段 | 预期路径 |
|---|---|
| P1 | `db/` 已有 DDL（不新建表结构除非缺列）；`ingest/sources/wind/tables.py`；`ingest/writers/tables.py`；`adapters/postgres/src_targets.py`；`contracts/schemas/pg/src.wind.asharemargintrade.yaml`；`contracts/visibility/src.wind.asharemargintrade.yaml`；`docs/contracts/src-wind-asharemargintrade.md`；对应 `tests/contracts/` |
| P2 | `lake/` 宇宙物化（现仅 `materialize/trade_calendar.py`）；`domain/ports/` 窄扩展 + lake/memory 适配器；`tests/unit/` + `tests/contracts/` |
| P3 | `features/spec/`、`features/library/sentiment/`、`features/panel/`、`features/registry/`；`tests/unit/features/` |
| P4 | `notebooks/` 探索；结论回 `docs/research/`；若 `strategy/backtest/vectorized/` 已可用则走它，否则不为此因子单开引擎 |
| P5 | 新 `src_*` schema / ingest / visibility（须先批新源） |

不改：`frozen/`、已发布 schema 的无关键、`apps/web/`、交易/密钥。
默认 `write_db=False`，且需要 `QUANTAGENT_ALLOW_DB_WRITE`。

---

## 6. 什么算本计划「做完」

本文件的交付已经完成：Charlie 可以按 P0→P5 往下做，而不用猜模块名。

**因子落地**另算，且按市场拆开：

- A 股正式式 `sr` 算完 = P0(Q1,Q2,Q5) 已裁定 + P1–P3 验收全过 + P4 至少有两融宇宙十分位与 `dtc_short` 对照（对照因子缺失必须写明，不能静默跳过）。
- 美股正式式 `dtc` 算完 = P0(Q3) 已批准并完成 P5。
- 本计划**不**把 Website / 组合准入算进完成。

---

## 7. 明确不做

- 不照搬美股 DTC 到 A 股融券端当正式表。
- 不把 NSI、AbTurn、换手、Amihud、BAB/MAX 当成这个因子。
- 不把 `_ingested_at` / `OPDATE` 当 SI 可见日。
- 不在非两融股票上估 SI。
- 不为对照因子先建通用工厂；不为港欧预留包。
- 不采购数据、不写密钥、不把研究结果当成交易指令。
