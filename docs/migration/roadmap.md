---
title: 迁移路线 P0–P6
status: active
created: 2026-09-16
updated: 2026-11-26
applies_to:
  - src/quantagent/
  - orchestration/
  - db/
  - frozen/
  - apps/web/
---

# 迁移路线 P0–P6

## 策略：strangler，不是大爆炸

旧仓 `pycharm_workspace` 在整个迁移期保持运行。新系统逐层接管，每接管一块
就把对应的旧调用切过来，直到旧仓无消费者才封存。

不采用"停下来重写再切换"，因为研究是持续进行的，停机成本不可接受；也因为
一次性切换的失败无法局部回滚。

## 阶段总览

| 阶段 | 内容 | 关键产出 |
|---|---|---|
| P0 | 骨架 | 目录结构、工程基建、设计文档 |
| P1 | 存储底座与时间语义 | PG 双面 schema、DuckDB 会话层、契约校验、因子布局 benchmark |
| P2 | 处置清单与数据入湖 | wx2 逐表清单、ETL 重写为 asset、发布时间可得性盘点 |
| P3 | 口径与因子 | domain 纯规则层、ports/adapters、golden test、因子长表 |
| P4 | 建模与策略 | Dataset/Estimator 抽象、回测语义合同、内核对照 |
| P5 | 发布与前端 | 冻结制品迁入、publish 契约、apps/web |
| P6 | 旧仓封存 | pycharm_workspace 转只读归档 |

## 当前进度 · 2026-11-25

**本节是项目唯一的进度入口（pipeline）。** 每完成一项就改这里：勾掉、补日期与提交号，新出现的阻塞写进
“阻塞与待裁定”。细节与证据放在下面链接的专题文档里，本节只写结论。各表实时行数用
`uv run quantagent ingest progress` 看（全部源 schema）。

### 阶段总状态

| 阶段 | 状态 | 一句话 |
|---|---|---|
| P0 骨架 | ✅ 完成 | 门禁 ruff / mypy / import-linter / pytest 全绿 |
| P1 存储底座 | ✅ 完成 | 两面迁移、DuckDB 会话、缺规则 fail-closed、因子布局 ADR |
| P2 处置与入湖 | 🔄 进行中 | Wind 已追平，11-25 起本机日更；Tushare 两表与宏观两源已日更；聚源 P0/P1 已回填；朝阳永续 P0/P1 已接入 |
| P3 口径与因子 | 🔄 进行中 | 股票池、成分、ST、前瞻收益与 14 个因子已对拍 wx2；剩 6 个因子与因子评价层 |
| P4–P6 | ⏳ 未开始 | |

### 运行环境

| 机器 | profile | 调度 | 托管 | 状态 |
|---|---|---|---|---|
| 公司电脑 | `office` | 无（11-25 起不注册调度） | Windows 计划任务 | 须拉新代码或停掉守护进程，避免与 Mac 重复采集 |
| Mac mini | `local` | 源：Wind 16:30、06:00，分钟 16:00、17:00，Tushare 19:00，朝阳永续 01:10，聚源 03:30，宏观 08:00、WGC 周日 12:00；因子：前瞻收益 17:30、00:00、02:00，分钟因子 19:30，cutamp/mif/moneyflowh/actlargemedcut 04:10，tr_umr/abso_umr 04:30 | launchd `com.quantagent.dagster-daemon`；网页 http://127.0.0.1:3000/ | 11-25 起承担全部日更 |

2026-11-21 负责人取消按机器划分源的写入职责；目标表白名单及写库保护保留。
两机队列独立，同一来源的自动采集不得跨机同时启用。

Dagster 运行存储都是各机本地 SQLite（[ADR](../adr/2026-11-17-dagster-local-run-storage.md)）。
Wind 与聚源采集在子进程里跑，600 秒无新页即终止（先 SIGTERM，10 秒后 SIGKILL）。因子日更按输入就绪判定增量，未就绪即跳过，次日补。

### P2 数据入湖明细

**Wind（第一批 30 张全部已接，另加 `AINDEXDESCRIPTIONZL`；Mac 接手回填）**：首次回填走独立作业 `orchestration/jobs/wind_initial.py`，按下表优先级串行（`c9db3c3`）；日更顺序不变。

| 优先级 | 表 | 状态 |
|---|---|---|
| 1 | `ASHAREST` | ✅ 3,358 行，与 wx2 一致（11-19） |
| 2 | `ASHAREEODDERIVATIVEINDICATOR` | ✅ 28,449,317 行（11-22）；0024 补 `TRADE_DT` 索引，单日读取 20 秒降到 0.2 秒。源表含周末行（2018 年以来 1,086 个非交易日），按日计数须先按交易日历过滤 |
| 3 | `ASHAREDESCRIPTION`、`ASHAREEODPRICES`、`ASHARECALENDAR`、`AINDEXEODPRICES` | ✅ 已追平。描述表 8,621 行对 wx2 8,635 行，差 14 行待核 |
| 3 | `AINDEXMEMBERS`、中信一二三级成分、`SWINDEXMEMBERS` | ✅（申万负责人已核验，11-22） |
| 3 | `AINDEXMEMBERSCITICSZL`（中信一级 canonical） | ✅ 8,633 行（11-22）；106 个月末与 wx2 一致。wx2 多 5 行是当前 Wind 源已不提供的旧行，测试中逐行登记核验 |
| 4 | 利润表、资产负债表、现金流量表、财务指标、业绩预告 | 🔄 利润表 2,478,908 行、财务指标 388,934 行已入库（11-22），其余三张未逐表核对；与 wx2 的键差见 [did_ratio ADR](../adr/2026-11-25-did-ratio.md) |
| 4 | `ASHAREDIVIDEND` | ✅ 156,872 行；wx2 多出的 3,448 键多为北交所与已退市旧代码，是否另有漏采待核（见交接第五节第 1 条） |
| 5 | 指数估值、中信行业行情、两融明细、两融汇总、停牌 | 🔄 部分；两融明细仅 5 万行 |
| 6 | `ASHAREMONEYFLOW` | ✅ 13,309,225 行，2012 起；0034 补 `(S_INFO_WINDCODE, TRADE_DT)` 索引；资金流三因子在用 |
| 6 | `CHINAMUTUALFUNDSTOCKPORTFOLIO` | 🔄 1,984 万行，旧仓仅一处读取 |
| 5 | `CBONDCURVECNBD`（只同步曲线 1232 的 10 个期限）、`CBONDCURVECSI`（只同步 0901、02502）、`FXEODPRICES`、`CBONDREPO`、`CBONDPRICESREPO`、`CBONDREPOANDIBLEODPRICES` | ✅ 已接采集与契约；0019 已执行（11-19），主键、`_batch_id` 索引、ingest 权限就绪；过滤条件在 wx2 上覆盖旧表全部行；随初始化回填进库 |
| 3 | `AINDEXDESCRIPTION`、`AINDEXDESCRIPTIONZL`（全表，各约 12 万行，not_pit） | ✅ 已接，0020 已执行（11-19）；`AINDEXINDUSTRIESCITICS` 改为视图（按中信一二三级成分筛选），随初始化回填出数 |

已入库数据在 11-17 用 `ingest wind verify` 重算指纹核对，业务值不一致 0。

字段说明只在契约 YAML 维护；PG 列注释由 `quantagent contracts emit-comments` 生成编号迁移（0021 已执行，1,081 列），测试防止两边漂移。Wind 说明已按 wind_db 的 `MS_Description`（11-20 导出）校正并补单位，0022 已执行。`S_DQ_ADJCLOSE_BACKWARD` 是前复权，含未来除权信息，研究读取不得使用。

**公开源与 Tushare（Mac）**：详见[宏观采集方案](macro-source-ingest-plan.md)

| 源 | 状态 |
|---|---|
| Tushare `shibor` | ✅ 40,008 行，与 wx2 逐值一致，19:00 日更 |
| Tushare `us_tycr` | ✅ 99,656 行，与 wx2 逐值一致，19:00 日更 |
| GPR 日频 | ✅ 91,770 行，08:00 日更，只存变化版本（C 级） |
| FRED/ALFRED | ✅ 15,824 个版本行，08:00 日更，分片取数（A 级） |
| 金十 ISM、WGC | ⏸ 暂缓到 P4，交给 Codex 调研取数方式 |

**聚源 JYDB P0/P1（Mac，2026-11-23）**：按[交接文档](jydb-ingest-plan.md)接入五张表，首次回填与当前源端 `COUNT(*)` 一致：`C_ED_MacroIndicatorData` 114,699、`C_ED_IndicatorMain` 92、`ED_MoneySupply` 660、`C_IN_IndicatorDataV` 367,928、`C_IN_IndicatorMain` 213。第二次增量五表均 pages=0。CPI `110255493` 全部 478 期与 wx2 的 `EndDate`、`InfoPublDate`、`DataValue` 逐期一致。按主键与 wx2 对拍：`C_ED_MacroIndicatorData` 本地多 9 个新 ID、`C_IN_IndicatorDataV` 多 17 个新 ID 且 wx2 多 1 个已在源端不存在的旧 ID，其余三表 ID 集合一致；差异均为源端新增或 wx2 残留。新增 `0027`（行业指标目录）、`0028`（`(JSID, ID)` 索引）、`0029`（契约列注释）。可见性契约与 PIT 的 `date_only`、`earliest + fixed_lag` 已实现；夜间 03:30 日更调度只在 Mac 注册。P2/P3 与朝阳永续未动。数据集名已由误写的 `c_in_indicatordav` 更正为 `c_in_indicatordatav`；旧名 368 条批次记录按 insert-only 规则保留为历史，新名已重建 368 条校验批次与游标。

**A 股 1 分钟行情**：▶ 2026-11-26 起暂用 MySQL 增量，16:00 首次、17:00 补跑；历史已追平至 2026-11-25，当日 1,344,536 行已入库并回读校验。东财暂缓，见 [来源裁定](../adr/2026-11-26-minute-bars-mysql-incremental.md)。PG 已执行 `0023_minprice_manifest.sql`。开盘价低于最低价不超过 0.5% 时保留源值并记录；MySQL 历史数据有负成交额的股票，置 0 后逐只与日成交额对比，差异严格小于 0.5% 才修正入库，否则排除当天该股票；缺少可比日行情同样排除，见 [处理 ADR](../adr/2026-11-22-minute-bar-negative-amount-daily-check.md)。2024-07-29 源表为空；2025-10-17 的 45 条与 2026-01-13 的 75 条负成交额经负责人单独裁定置 0，整日入库核验，见 [10 月 ADR](../adr/2026-11-22-minute-bar-october-17-correction.md) 与 [1 月 ADR](../adr/2026-11-22-minute-bar-january-13-correction.md)。2026-01-19 的 152 条负成交额涉及 85 只股票，按新标准修正 6 只、排除 79 只后入库 1,302,825 行；2026-01-21 排除 67 只异常股票后写入其余 5,419 个代码、1,305,961 行，两个指数的 3 条负成交额按既有规则置 0；该分区读取会阻止将其误认为完整，见 [裁定](../adr/2026-11-22-minute-bar-january-21-exclusions.md)。2026-01-22 的 `002485.SZ` 15:00 成交量 -1 和成交额 -28 按负责人裁定置 0，当天 1,321,868 行已入库校验，见 [裁定](../adr/2026-11-22-minute-bar-january-22-correction.md)；2026-03-26 的 `920242.BJ` 15:00 成交量 -1、成交额 -31 按负责人裁定置 0，当天 1,326,683 行已入库校验，见 [裁定](../adr/2026-11-22-minute-bar-march-26-correction.md)；2026-04-16 的 `920855.BJ` 15:00 成交量 -1、成交额 -37 按负责人裁定置 0，当天 1,329,580 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-april-16-correction.md)；2026-04-30 的 `920608.BJ` 15:00 成交量 -1、成交额 422 按负责人裁定置 0，当天 1,331,222 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-april-30-correction.md)；2026-06-02 的 `920112.BJ` 15:00 成交量 -1、成交额 1037 按负责人裁定置 0，当天 1,334,389 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-june-02-correction.md)；2026-06-08 的 `920608.BJ` 15:00 成交量 -1、成交额 -51 按负责人裁定置 0，当天 1,334,635 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-june-08-correction.md)；2026-06-22 的 `920855.BJ` 15:00 成交量 -1、成交额 -7 按负责人裁定置 0，当天 1,335,353 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-june-22-correction.md)；2026-06-29 的 `920608.BJ` 15:00 成交量 -1、成交额 11 按负责人裁定置 0，当天 1,335,113 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-june-29-correction.md)；2026-07-06 的 `920455.BJ` 和 `920541.BJ` 15:00 记录成交量和成交额按负责人裁定置 0，当天 1,335,120 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-july-06-correction.md)；2026-07-08 的 `920132.BJ` 15:00 成交量 -1、成交额 -56 按负责人裁定置 0，当天 1,335,361 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-july-08-correction.md)；2026-07-09 的 `920422.BJ` 15:00 成交量 -1、成交额 337 按负责人指示置 0，当天 1,335,361 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-july-09-correction.md)；2026-07-14 的 `920422.BJ` 15:00 成交量 -1、成交额 11 按负责人指示置 0，当天 1,335,126 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-july-14-correction.md)；2026-07-15 的 `920112.BJ`、`920168.BJ` 15:00 记录成交量与成交额按负责人指示置 0，当天 1,335,368 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-july-15-correction.md)；2026-07-17 的 `920121.BJ` 15:00 成交量 -1、成交额 2063 按负责人指示置 0，当天 1,335,124 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-july-17-correction.md)；2026-07-22 的 `603869.SH`、`920108.BJ` 15:00 记录成交量与成交额按负责人指示置 0，当天 1,335,849 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-july-22-correction.md)；2026-07-24 的 `920112.BJ` 15:00 成交量 -1、成交额 -12 按负责人指示置 0，当天 1,335,608 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-july-24-correction.md)；2026-07-28 的 `920370.BJ` 15:00 成交量 -1、成交额 129 按负责人指示置 0，当天 1,336,322 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-july-28-correction.md)；2026-08-04 的 `920395.BJ` 15:00 成交量 -1、成交额 91 按负责人指示置 0，当天 1,337,051 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-august-04-correction.md)；2026-08-17 的 `920121.BJ` 15:00 成交量 -1、成交额 1462 与 `920679.BJ` 15:00 成交量 -1、成交额 10 按负责人指示置 0，当天 1,339,222 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-august-17-correction.md)；2026-08-20 的 `920146.BJ` 15:00 成交量 -1、成交额 37 与 `920395.BJ` 15:00 成交量 -1、成交额 -42 按负责人指示置 0，其中 920395.BJ 负成交额按日行情对比通过（分钟与日成交额均为 2,857,887 元），当天 1,339,943 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-august-20-correction.md)；2026-08-24 首次出现三条 15:00「成交量 -1」记录（`920168.BJ` 378、`920275.BJ` -62、`920679.BJ` -37），类型与此前一致，按负责人惯例指示置 0，两条负成交额经日行情对比均完全一致，当天 1,340,428 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-august-24-correction.md)；2026-09-10 的 `920177.BJ` 15:00 成交量 -1、成交额 971 按负责人指示置 0，当天 1,340,191 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-september-10-correction.md)；2026-09-15 的三条 15:00「成交量 -1」记录（`920121.BJ` 205、`920166.BJ` 2、`920168.BJ` 542，成交额均为正）按负责人惯例指示置 0，当天 1,339,950 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-september-15-correction.md)；2026-09-17 的 `920242.BJ` 15:00 成交量 -1、成交额 -3 按负责人指示置 0，负成交额经日行情对比通过，当天 1,341,155 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-september-17-correction.md)；2026-09-28 的 `920055.BJ` 15:00 成交量 -1、成交额 168 按负责人指示置 0，当天 1,340,680 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-september-28-correction.md)；2026-09-30 的 `920163.BJ` 15:00（-1 手、-3 元）、`920541.BJ` 15:00（-1 手、-17 元）按负责人指示置 0，同日 `920395.BJ` 15:00（成交量 0、成交额 -24）只由既有日行情对比规则处理；三条均通过对比，当天 1,341,403 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-september-30-correction.md)；2026-10-08 的三条 15:00「成交量 -1」记录（`920033.BJ` -29、`920541.BJ` -7、`920781.BJ` -17）按负责人指示置 0，三条负成交额均通过日行情对比，当天 1,340,439 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-october-08-correction.md)；2026-10-12 的 `920166.BJ`（-1 手、404 元）、`920541.BJ`（-1 手、619 元）按负责人指示置 0，当天 1,341,644 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-october-12-correction.md)；2026-10-13 的 `920069.BJ`（-1 手、-44 元）、`920080.BJ`（-1 手、-41 元）按负责人指示置 0，同日 `920541.BJ`（成交量 0、成交额 -54）只由既有日行情对比处理；三条均通过对比，当天 1,341,403 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-october-13-correction.md)；2026-10-14 的 `920020.BJ` 15:00（-1 手、13 元）按负责人指示置 0，同日 `920108.BJ`（成交量 0、成交额 -55）只由既有日行情对比处理，当天 1,342,126 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-october-14-correction.md)；2026-10-19 的 `920242.BJ` 15:00（-1 手、20 元）按负责人指示置 0，当天 1,342,125 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-october-19-correction.md)；2026-10-21 的 `920145.BJ`（-1 手、18 元）、`920957.BJ`（-1 手、761 元）按负责人指示置 0，当天 1,343,090 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-october-21-correction.md)；2026-10-22 的 `920751.BJ` 15:00（-1 手、37 元）按负责人指示置 0，当天 1,343,572 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-october-22-correction.md)；2026-10-27 的三条 15:00「成交量 -1」记录（`920027.BJ` -53、`920455.BJ` -56、`920675.BJ` -31）按负责人指示置 0，三条负成交额均通过日行情对比，当天 1,343,572 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-october-27-correction.md)；2026-10-29 的 `920871.BJ` 15:00（-1 手、37 元）按负责人指示置 0，当天 1,343,572 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-october-29-correction.md)；2026-11-03 的 `920275.BJ`（-1 手、-35 元）、`920931.BJ`（-1 手、263 元）按负责人指示置 0，同日 `920030.BJ`（成交量 0、成交额 -55）只由既有日行情对比处理，当天 1,343,571 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-november-03-correction.md)；2026-11-11 的 `920608.BJ` 15:00（-1 手、-19 元）按负责人指示置 0，负成交额经日行情对比通过，当天 1,344,777 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-november-11-correction.md)；2026-11-18 的 `920121.BJ` 15:00（-1 手、1775 元）按负责人指示置 0，当天 1,344,295 行已入库校验，见 [裁定](../adr/2026-11-23-minute-bar-november-18-correction.md)；2026-11-19 入库 1,344,295 行，2026-11-20 与 11-21 已登记分区内容一致、按既有逻辑跳过未覆盖。**历史回填已到目标终点 2026-11-20**：07-29 至 11-20 共 77 个交易日全部分区在册，`ingest minprice verify` 报已登记 560、未登记 0、错误 0，全程日志 `var/logs/minprice-backfill-after-20260804.log`；2026-11-23 经负责人追加同步，当日源数据无负成交量、负成交额和重复键，1,343,572 行已入库校验，覆盖扩展为 07-29 至 11-23 共 78 个交易日、`verify` 已登记 561、未登记 0、错误 0。2026-11-24 的 `920608.BJ` 15:00 成交量 -1、成交额 353 按负责人既定同类处理裁定置 0，当天 1,345,018 行已入库校验，见 [裁定](../adr/2026-11-25-minute-bar-november-24-correction.md)。源数据含三板做市指数，股票与指数范围需另行裁定。2026-11-25 东财 16:00 首次及 17:00 补跑均在股票列表分页遭 HTTP 502 失败，随后已从 MySQL 补齐当日，见 [修正裁定](../adr/2026-11-26-minute-bar-november-25-correction.md)；负责人改用 Wind 上市描述表生成当日采集名单，当前态仅用于采集不作为 PIT 研究池，见 [裁定](../adr/2026-11-25-minute-bar-wind-stock-list.md)；切换 Wind 名单后东财第一只股票分钟接口仍报 ProxyError，东财来源未成功登记分区；东财域名被系统 Clash Fake IP 解析到 198.19 网段，禁用 requests 系统代理后连接仍被关闭，直接指定 DNS 解析地址也返回 502，尚无法区分东财端故障与网络网关问题。东财全市场验证仍待完成；两项日更调度已切换 MySQL 并启用，代码默认状态仍为停止。见 [来源 ADR](../adr/2026-11-21-minute-bars-source-split.md) 与 [接入方案](minute-bar-ingest-plan.md)。

**朝阳永续 Suntime P0/P1（2026-11-24）**：按[交接文档](suntime-ingest-plan.md)接入五张表。个股两张与 `rpt_earnings_adjust` 用 0006 已建的表；指数两张（`con_forecast_idx`、`con_forecast_roll_idx`）由 0030 新建，源库有、wx2 没有，负责人裁定为 P0。0031 给五张表加 `(tmstamp, id)` 游标索引，0032 写契约列注释。可见性只配四张一致预期：`source_field con_date`、非 strict、等级 A，个股年度表的 `con_date` 是 timestamp，按日期比较；`rpt_earnings_adjust` 只建镜像、不写契约。`con_forecast_stk_ttm` 不同步、不进写入白名单。中文用 pymssql `charset=utf8` 直接读取，不再做旧仓的 latin1/GBK 再解码。日更 01:10，避开旧仓 22:00、02:00、04:30 与聚源 03:30，只在 Mac 注册。P2（`FIN_APPO_RELE_DATE`、`der_prob_excess_stock`、`der_diver_stk`）未动。

**其他**：JYDB P2/P3 七张表、朝阳永续 P2 三张、Tushare 其余接口 ⏳ 未接；第四类运维表 ⏳ 未动。

### P3 口径与因子

| 项 | 状态 | 前提 |
|---|---|---|
| `all_a` 股票池（读取时计算） | ✅ 真实库 2,145 个金样本日：2,138 天与 wx2 一致，7 个已知例外日按预期不同（11-22，测试只读 PG） | — |
| 指数 / 行业成分池 | ✅ 真实库 4 宽基 × 85 月末与 wx2 一致（11-20）；申万表负责人已核验（11-22）。`citics1` 改读 `AINDEXMEMBERSCITICSZL`（[ADR](../adr/2026-11-22-citics-l1-members-zl.md)），真实库 106 个月末与 wx2 一致 | — |
| ST 状态 | ✅ 真实库 202 个月末与 wx2 一致（11-20） | — |
| cutamp、tr_umr | ✅ 2024-01-05 全截面 golden：cutamp 5,076 只全部一致（278 只旧表多出：北交所旧代码 234、已退市 44）；tr_umr 4,861 只中 4,858 一致，3 只已知差异。cutamp 按旧仓 quicksort 并列顺序升 `v2`（[ADR](../adr/2026-11-22-cutamp-legacy-quicksort-order.md)），lake 已补 34 行 v2 | — |
| 旧网关 golden（已有新端口的方法） | ✅ 股票池、成分池、ST、日行情、交易日历（8,770 天）、指数涨跌幅（`000985.CSI`、`h30269.CSI`）均与 wx2 一致（11-22）。`core/` 三个网关共 51 个公开读取方法，12 个无现役调用；其余多为择时/宏观研究线读取，随 P4 各线迁移、建端口时先做 golden | — |
| `pit_grade` 木桶、长表写入校验 | ✅ 两层依赖图含 D 输出 D；写入拒绝 A–D 以外的等级与早于 `event_dt` 的 `knowledge_dt`（11-22）。写入时比对完整血缘需改接口，未做 | — |
| `mart.forward_return` 股票 open-to-open | ✅ 代码与 wx2 对拍完成（29 个样本日 5D/10D，all_a 内差异全部登记核验；[ADR](../adr/2026-11-22-forward-return-open2open.md)）。已物化 2018-01-02 起，四个周期共 37,360,480 行；11-25 起日更（17:30、00:00、02:00） | — |
| `alpha_factory` 因子批量移植 | 🔄 Current-20 共 20 个，已迁 14 个，均与 wx2 对拍（其他差异 0，各类差异逐行核验）并物化到 lake（as_of 2026-11-20 前后）：cutamp v2、tr_umr v2（[ADR](../adr/2026-11-24-tr-umr-v2-no-missing-as-zero.md)，11-25 补齐 2018 起全历史）；分钟 7 个，2024-08 起（[第一批](../adr/2026-11-24-minute-factors-first-batch.md)、[2b](../adr/2026-11-24-minute-factors-batch-2b.md)，core_up/down 按 pxret21 中性化存残差）；资金流 3 个，2018 起（[ADR](../adr/2026-11-24-moneyflow-factors-batch-2a.md)）；mif，2018 起（[ADR](../adr/2026-11-24-mif.md)）；did_ratio 2018 起（[ADR](../adr/2026-11-25-did-ratio.md)，11-26 物化 872 万行 + 接入 04:10 日更）。11-25 起本机日更（输入就绪才增量）。剩 6 个：event_sue、event_delta_roe、event_aog、barra ERNQLT、barra SENTIMENT、nap_adj_ratio | 见交接第二节 B |

### 下一步

见下文「交接与后续规划」第二节，按 A → B → C 推进，D、E 可穿插。

### 交接与后续规划（2026-11-25，接任者先读本节）

#### 一、状态快照（2026-11-25 21:30）

- **调度**：全部日更挂在 Mac 本机 Dagster（`local`），共 13 个调度，网页 http://127.0.0.1:3000/（Overview → Timeline 能看到未来的计划触发）。
  11-25 首日：Wind 16:30 成功（12 分钟，补齐 11-23 至 11-25 日行情）；前瞻收益 17:30 成功，已增量到 `end_dt` 11-25；分钟因子 19:30 成功，增量到 11-24；
  东财分钟 16:00、17:00 两次失败（HTTP 502 / ProxyError，另一会话处理中），所以分钟因子停在 11-24。cutamp/mif/资金流 04:10 与 UMR 04:30 今晚首次增量。
  `AINDEXEODPRICES` 在 16:30 只到一部分（11-25 2,134 / 6,730 行），06:00 那轮补齐；日更就绪判定会按基准代码等待。
- **lake 已物化**：前瞻收益 open-to-open 四个周期（2018 起）；14 个因子（cutamp v2、tr_umr v2、mif、资金流 3 个、did_ratio 为 2018 起；分钟 7 个为 2024-08 起）。
  did_ratio 11-26 完成物化：2018-01~2026-10 共 106 个月、872 万行、pit_grade 全 B、golden 2024-05-15 一致率 99.32%；同日接入 04:10 日更（`8aa7679`），已增量到 2026-11-25。
- **Current-20 进度**：14 / 20 已迁。剩 6 个：`event_sue`、`event_delta_roe`、`event_aog`、`barra_cne6_ernqlt`、`barra_cne6_sentiment`、`nap_adj_ratio`。
- **工作区里有其他会话的未提交改动**（朝阳永续、东财分钟、`universe.py` 与 `domain/ports/universe.py`、`AGENTS.md`、`settings.py` 等）。
  它们让 3 个迁移清单测试在工作区失败（`test_migrate`、`test_src_migrations` ×2），提交后应恢复；不要替它们提交或回退。

#### 二、后续规划（按优先级）

**A. 运维加固（先做，1–2 天）**
1. **失败告警**：✅（11-26，`d2243f0`）`@run_failure_sensor` 监控全部日更作业，step 失败取首行错误摘要落 `var/logs/alerts/run_failures.jsonl`；`quantagent alert summary` 生成前日汇总到 `var/logs/alerts/summary/`。daemon 已重启，sensor 运行中。**通知渠道（邮件/企业微信）仍待负责人定**——渠道接入后读同一 JSONL/汇总文件。东财分钟、Tushare、宏观采集不走 ToDesk 分页链路，无看门狗需求。
2. **其余来源的看门狗**：✅（11-26）朝阳永续随 `0b85ce0` 接入看门狗（`resources/suntime.py`）；手动 `quantagent ingest jydb/suntime sync` CLI 已接看门狗（`4fb61ae`，机制下沉 `quantagent.ingest.watchdog` 为唯一事实源，`orchestration.resources.watchdog` 改为 re-export）。
3. **公司电脑停掉守护进程**或拉新代码（office 调度已清空），否则与 Mac 重复采集。
4. **daemon 的 PG 用户**从超级用户 `leo` 改为 `quantagent_ingest`（待负责人放密码）。
5. **源数据修订不回溯**：因子日更只往后增量，Wind 事后修订的源值不会触发已写因子重算。需设计"源表 `_batch` 的修订行 → 受影响 (代码, 日期) → 新增修订身份或重算"的机制，写 ADR 后实施。
6. 日更 run log 的就绪依据只进了 `input_digest`（不可读），可读版在 Dagster 元数据；如需审计，给 `RunLog` 加可读字段。

**B. 收尾 Current-20（剩 6 个）**
1. ~~**did_ratio 物化**~~ ✅（11-26）物化完成 + 接入 04:10 日更，见上。
2. **事件三因子**（`event_sue`、`event_delta_roe`、`event_aog`，旧 `factors/factor_event_2.py:383-540`）：先读旧仓 `docs/decisions/2026-08-31-performance-factor-event-pit.md`（事件 PIT 以 `confirm_date` 截止）。
   要重建旧派生表 `fin_income_gen`（仓内无生产代码，需从使用处反推）与业绩快报来源（契约里未见快报表，先确认 Wind `ASHAREPROFITEXPRESS` 是否需要接入，属于新增源表，要问负责人）。
   `event_aog` 另需指数开盘价：`IndexReturnRepository` 只有涨跌幅，需窄扩展字段；旧代码开盘日判定 `'0925'` 与 `event_high250` 的 `'0930'` 不一致，迁移时要请负责人定。
3. **nap_adj_ratio**（`factors/factor_rpt.py:49-56`）：数据来自朝阳永续 `rpt_earnings_adjust`（已镜像入库、未写可见性契约）。需先按旧仓下游反推可见性写契约；"报告数最多的年度"有并列，按 `_legacy_sort` 原则复现。
4. **barra SENTIMENT**（`enhanced_optimizer/factors/exposure.py:707-750`）：一致预期四张表已入库（`con_forecast_*`，可见性 A）。旧值在 `wx2.barra_cne6`，trade_date t 映射 adj_date=next(t)（`alpha_factory/data_gateway.py:1112-1123`），对齐要先查清。
5. **barra ERNQLT**：需要整套 CNE6 暴露引擎（`exposure.py` 的 `RAW` 族、行业 `l3integrate`、市值加权），工作量最大，放最后；可能要把 Barra 作为独立子项目（暴露全集而非单因子），先与负责人确认范围。

**C. 因子评价层（P3 收尾的核心，B 进行中即可并行设计）**
旧仓 `alpha_factory` 日更不止算因子，还产出 `alpha_factory_metric_d`（IC/RankIC 等）、`group_nav_d`（分组净值）、`factor_snapshot_d`、`alert_d`、`exposure_d`、`factor_corr_d`。
新仓已有契约 `feature.metric`、`signal.group_nav`（`contracts/schemas/lake/`）与 domain 类型，但没有计算与物化。按 [多周期 ADR](../adr/2026-09-19-factor-horizons-and-admission.md)：
主协议 `oo_5d`，逐周期（1/5/10/20D）独立报告 IC、ICIR、RankIC、G10-G1、单调性、覆盖率；`knowledge_dt` = max(因子, 前瞻收益 `end_dt`)。
步骤：先对旧 `metric_engine.py`、`group_backtest.py`、`refresh_factor_metrics*.py` 做 golden（对拍 wx2 `alpha_factory_metric_d` 与 `group_nav_d`），再实现。注意旧 IC 用 total 收益、`ret_oo_5d`，旧 1D 路径（`stock_ratio`）有日期错位，见前瞻收益 ADR。

**D. P2 剩余数据**
JYDB P2/P3 七张、朝阳永续 P2 三张（含 `der_prob_excess_stock`，接入时实现"任一字段早于调仓日"可见性规则）、Tushare 其余接口（旧仓 `tushare_ths_industry` 18:20、`tushare_data` 08:30 只迁了两张）、第四类运维表。
Wind 财报四张与业绩预告的回填是否追平未逐表核对（利润表本地 2,478,908 行对 wx2 2,726,201 行，差额主要是 wx2 同键重复与北交所旧代码，见 did_ratio ADR）。

**E. P4 研究线与回测**
旧调度里的研究展厅链路（风格轮动、宏观 regime、债券/黄金/美股择时、Core5 多资产、ETF 因子与行业轮动、`optimizer_exposure`、`style_crowd_data`、`stock_hq_score`）均未迁。
按 roadmap P4：先定回测语义合同，再迁内核；每条研究线迁移前先为它用到的 `MarketDataService` 方法建端口与 golden（11-22 盘点：51 个公开读取方法，有端口的已全部 golden）。
跨时区可见性（美债、ISM）的规则引擎扩展在第一个读取方出现时实现。旧仓推送类任务（企业微信、邮件）属于生产边界外，迁移前先问负责人。

**F. P5 发布与 P6 封存**：按下文各阶段验收标准执行，P6 需新系统独立跑满一个完整业务周期（含月末、季末、财报季）。

#### 三、环境与协作的坑（必读）

1. **Mac 的 Dagster daemon 直接加载工作区代码**（`workspace.yaml` 的 `working_directory` 指向仓库）。未提交的改动会立刻生效，包括新调度。改 `orchestration/` 前想清楚会不会触发真实运行。
2. **不要执行裸 `uv sync`**：它会卸掉可选依赖组（Dagster 在 `orchestration` extra 里），守护进程立即报 `No module named dagster`。需要同步时用 `uv sync --all-extras`。
   **不要在仓库目录以外执行 `uv run`**（例如临时 git worktree 里）：它会把共享 `.venv` 的 editable 安装改指到别处。在别的目录验证时直接调用 `.venv/bin/python`、`.venv/bin/mypy`，加 `PYTHONPATH=<dir>/src:<dir>`。日常用 `uv run --no-sync`。
3. **多会话共用一个工作区**：提交时只暂存自己的文件；共享文件（`roadmap.md`、`docs/adr/README.md`、`orchestration/definitions.py` 等）用"HEAD 版本 + 自己的改动"生成索引内容（`git hash-object -w` + `git update-index --cacheinfo`），不要整文件 `git add`。
   提交前在干净 worktree 上跑一遍门禁（见第 2 条的调用方式）。
4. **pre-commit 的 end-of-file-fixer** 会改 JSON fixture 末尾换行并中止提交，重新 `git add` 后再提交即可。
5. **wx2 与 wind_db**：wx2 用 `get_settings().legacy_mssql_*`，wind_db 用 `wind_mssql_*`；端口以 `.env` 为准（11-24 起有变化）。负责人曾要求 Wind 同步期间不访问 wind_db（抢 ToDesk 带宽），访问前先问。脚本连接后用 `SELECT DB_NAME()` 断言库名。
6. **写库与迁移**：`PGOPTIONS="-c lock_timeout=10s" QUANTAGENT_ALLOW_DB_WRITE=true uv run --no-sync quantagent db migrate --plane src --write-db`；变量只放在单条命令上，不 export。src 迁移当前到 0034（0030–0033 为他人）。
7. **批量物化脚本**：每段命令检查退出码，失败即停（11-24 曾因管道吞掉退出码漏写一个月）。lake 写入不覆盖、遇重复身份报错；改口径就升 `definition_version`，旧版本行保留。
8. **单并发队列**：任何一个卡住的 run 会堵住后面所有调度。终止方法：`instance.run_launcher.terminate(run_id)`；进程不退出时依次 KILL 步骤子进程与 run worker，再 `report_run_canceled`。
9. 数据集查询要点：`ASHAREEODDERIVATIVEINDICATOR` 含非交易日行，按日计数先按交易日历过滤；`S_DQ_ADJCLOSE_BACKWARD` 是前复权，研究不得使用；分钟数据有排除股票日（分区元数据 + 常量），经 `MinuteBarRepository.excluded_codes` 取得。

#### 四、口径与方案要点（已定，后续因子照此）

1. **迁移先固化旧行为（§7.10）**，差异必须逐行解释。golden 做法：wx2 旧值按截面日列式存 fixture（每文件 < 512KB），差异分类后**逐行核验**：已裁定口径差异 / 源数据差异（存 wx2 原始行，代入新函数复现旧值）/ 旧表陈旧（wx2 自身输入复现不了旧值，且本地值等于 wx2 输入重算值）/ 其他（必须为 0）。
   旧表有不可复现时段时按月抽样找出可复现区间，golden 只取区间内日期并写进 ADR。`tests/golden` 已约 15MB，后续优先存摘要、按需下钻。
2. **缺失原则**：缺失不补 0、无定义不写 0（ratio 假 0、pandas 零方差峰度、缺输入回退都改为不产值）；有经济含义的 0 保留（did_ratio 的"未分红""亏损无派息能力"）。端点或窗口内停牌视为缺失。
3. **股票域**：逐截面日取 `all_a`（`cli/_universe.py`），不用区间末日成员回填全区间。`all_a` 依赖当日衍生指标两个市值字段都有值。
4. **并列顺序**：旧仓 pandas 默认 quicksort 的并列顺序用 `features/library/_legacy_sort.py` 的纯 Python 移植复现（含堆排序兜底），不调 `np.argsort`（x86 SIMD 下并列顺序随机器变）。
5. **精度**：旧输入以舍入后的值存表时，按旧输入精度舍入（mif 的 `night_ratio` 四位）；比对按旧表存储精度。
6. **中性化**只适用于带 `_neut_pxret21` 后缀的因子：IC 检验路径（MAD 去极值、样本下限 20、pxret21 两端价配对），长表存残差不存 z-score。
7. **财报类**：同报告期取公告日最大的一条；同 (代码, 报告期, 公告日) 取值不同则跳过该股该日。
8. **前瞻收益**：`event_dt` = 信号日 T，T+1 开盘到 T+h+1 开盘，后复权开盘价，`knowledge_dt = end_dt`，`return_leg` 进主键，只做 total；`usage: evaluation_only`，不得进训练特征。
9. **日更**：从 lake 最大截面日往后增量；输入当日行数达前 5 个开市日最大值的 99% 才算就绪，遇第一个未就绪日停；lake 为空报错，不自动全量。

#### 五、待负责人裁定

1. ~~**did_ratio 物化前的源端漏行**~~ ✅ **已裁定可物化**（11-26 核查，负责人已放行 wind_db）：直接对 wind_db 源端 OBJECT_ID 差集对比本地 PG（不经 wx2）。分红漏采 4 行、利润表漏采 66 行，**全部是当日（11-26）新增待日更**，非历史漏采；本地零残留；共有键抽 300 行值零不一致。wx2 独有的 3,448/3,559 键是 wx2 陈旧快照残留（北交所旧代码、已退市，Wind 源端已删）——反证：wx2 多余北交所分红键数超过源端全部北交所行数（2,448 行）。证据见 [did_ratio ADR 核查结论](../adr/2026-11-25-did-ratio.md)。**无需补采，可物化。**
2. **告警渠道**（A.1）：邮件、企业微信或其他。
3. **源数据修订后的因子重算机制**（A.5）是否现在做。
4. **事件因子**需要的新源表（业绩快报等）与开盘日判定阈值（`'0925'` / `'0930'`）。
5. **Barra 范围**：只迁 ERNQLT、SENTIMENT 两个单因子，还是迁整套 CNE6 暴露（`optimizer_exposure` 也依赖）。

### 阻塞与待裁定

| 事项 | 等谁 |
|---|---|
| ISM、美债等跨时区数据的可见性：按消费市场收盘时刻判断，需扩展规则引擎 | 已裁定；随 P4 金十或第一个美债读取方实现（11-22 负责人同意推迟）。消费市场由调用方传入还是写在契约里，届时再定 |
| 朝阳超预期 `der_prob_excess_stock` 的「任一字段早于调仓日」规则 | 随 E 线朝阳永续接入实现（11-22 同意推迟） |
| ToDesk 链路会吞连接：回填靠看门狗与逐列回读兜底，未根治 | 观察 |
| daemon 连 PG 用超级用户 `leo`，应改 `quantagent_ingest` | 负责人放密码 |

专题文档：[Wind 交接](wind-pipeline-handoff.md)、[宏观采集方案](macro-source-ingest-plan.md)、
[wx2 清单](wx2-table-list.md)、[ADR 索引](../adr/README.md)。

### 阶段概况

| 阶段 | 概况 |
|---|---|
| P0 | 完成。门禁 ruff、mypy、import-linter、pytest 全绿 |
| P1 | 完成。两面迁移可独立 migrate/status，DuckDB 会话、缺规则 fail-closed 测试、因子布局 ADR 均已落地 |
| P2 | 进行中。明细见上文「P2 数据入湖明细」 |
| P3 | 进行中。明细见上文「P3 口径与因子」；剩因子批量移植 |
| P4–P6 | 未开始 |

P3 先于 P2 验收起步是有意的：用第一个因子把采集、PIT 读取、长表写入整条链路跑通。
P2 的验收标准仍是 P3 收尾的前提。

---

## P0 骨架（本次交付）

### 内容

仓库初始化、工程基建配置、设计文档。不写任何业务逻辑代码。

### 验收标准

- `uv sync` 成功，`uv run ruff check .`、`uv run mypy`、
  `uv run lint-imports` 全部通过（当前无代码，等于验证配置本身有效）
- 目录骨架完整，每个分层包的 `__init__.py` 有职责 docstring
- `docs/` 下所有文档 frontmatter 完整
- `.gitignore` 十几行，`var/` 整体忽略，`frozen/` 与 `publish/` 入库

### 回滚点

无需回滚——P0 不触碰旧仓任何内容。

---

## P1 存储底座与时间语义

### 内容

1. PG 双面 schema 建立（`db/migrations/src/` 与 `db/migrations/ops/`）
2. `platform/` 的配置、日志、run log、digest、DuckDB 会话层
3. `contracts/` 的 schema 与 visibility 规则加载与校验
4. **因子长表物理布局 benchmark**：分区键、目标文件大小、排序键、压缩，
   出 ADR 后才固化 Parquet 约定

源拉取的批次原样归档（`_vintage/`）已取消，见
[../adr/2026-09-17-no-source-vintage-archive.md](../adr/2026-09-17-no-source-vintage-archive.md)。

### 为什么 benchmark 在这里

物理布局一旦固化，改起来要重写全部历史数据。在写入任何真实因子之前完成
benchmark，代价最低。

### 验收标准

- 两条迁移序列可独立 `migrate` 与 `status`
- DuckDB 会话能挂载 Parquet 并跑通三类代表性查询
- 至少一个数据集有完整契约（schema + visibility + `reads`），且缺规则时
  CI 确实失败
- benchmark 结论 ADR 已定版，脚本保留在仓库

### 回滚点

PG schema 可整体 drop 重建（此时无真实数据）。`var/lake/` 可整体删除。
不影响旧仓。

---

## P2 处置清单与数据入湖

### 内容

1. **先产出 `wx2` 逐表处置清单**（标准见 [wx2-disposition.md](wx2-disposition.md)，清单见 [wx2-table-list.md](wx2-table-list.md)）。清单已产出，迁入进行中，见上方当前进度。
2. 按类别分别执行：源数据迁 `src_*`，派生数据不迁，不可重算历史冻结到
   `var/lake/legacy/`，控制状态重新建模到 `ops_*`，无消费者不迁
3. Wind / Tushare / JYDB / 朝阳永续 / 宏观 ETL 重写为 Dagster asset
4. **逐源逐表按旧仓下游取数规则定 visibility**（`data_gateway` 等），
   缺证据或冲突再问；写 `pit_grade` / `pit_from`
5. 文档与制品处置清单已产出（见 [docs-and-artifacts-list.md](docs-and-artifacts-list.md)；执行在 P5）

### 顺序约束

**清单已产出，迁入进行中。** 先迁一部分再补清单，会出现"已经迁进来但发现
应该不迁"，而删除已迁入的数据比一开始不迁麻烦得多。类别 1 补收录仍须
负责人确认；visibility 从旧仓下游反推，不必每张表先送审。

### 验收标准

- 每张 `wx2` 表都在清单中有归属与判定依据，无归属的表为零
- 每个迁入的数据集有 visibility 规则，`grade` 与 `rationale` 齐全
- 存量迁入的数据集全部标注 `pit_recoverable: false` 与 `pit_from`
- `std` 与 `mart` 层有第一批资产可物化，血缘图完整
- 写入保护的六条约束各有测试覆盖且通过
- 文档与制品清单完成（用于保护冻结制品不被误删）

### 回滚点

`src_*` 可按表 drop 重新迁入（源数据可重新拉取）。`var/lake/legacy/` 冻结
后不可重建——因此它的迁入要在清单定版之后，且迁入前做一次独立备份。

旧仓在此阶段仍是权威，任何不一致以旧仓为准。

---

## P3 口径与因子

### 内容

1. `domain/` 纯规则层落地：calendar、adjust、identity、pit、universe、
   classification
2. `domain/ports/` 的 Protocol 与三套适配器
3. **先把旧仓口径固化成 golden test**：`BaseDataGateway`、
   `UniverseProvider`、`MarketDataService` 及各研究线网关
4. 新实现对拍通过
5. `feature` 长表与 `knowledge_dt` / `pit_grade` 血缘推导
6. `factors/` 与 `alpha_factory/` 的因子移植

### 顺序约束

**golden test 先于新实现。** 顺序颠倒的话，新实现的行为会变成基线，口径
漂移无从发现。

### 验收标准

- `tests/unit/domain/` 全部在零数据库零文件条件下通过
- `tests/contracts/` 三套适配器行为一致
- `tests/golden/` 覆盖旧仓四类网关的口径，差异全部有解释并记入 ADR
- 因子长表写入时拒绝人工传入 `knowledge_dt` 与 `pit_grade`
- `pit_grade` 木桶继承有测试：构造含 D 级输入的依赖图，断言输出为 D
- 不存在无 `as_of` 的读取路径（接口层面校验）
- 重算的因子与旧库交叉校验完成，差异有解释

### 回滚点

因子可重算，整层可删除重建。domain 与 adapters 是纯代码，git revert 即可。

此阶段开始出现"新旧并行"：同一个因子新旧两份值。以旧仓为权威直到交叉校验
通过。

---

## P4 建模与策略

### 内容

1. `Dataset` / `Splitter` / `Estimator` / `Pipeline` / `Evaluation` 抽象
   落地，WLS 与截面 OLS 迁入 `estimators/linear/`
2. **先定版回测语义合同**并让各内核输出统一结果 schema
3. `rebalance` 内核（继承 `BacktestEngine` 语义）
4. `vectorized` 内核（继承 `group_backtest` 语义）
5. 用行为对照测试逐对判定是否合并
6. 策略与 Agent 移植

### 顺序约束

**合同先于内核。** 没有统一的结果 schema，"行为一致"连比什么都说不清。
见 [../adr/2026-09-16-backtest-contract-first.md](../adr/2026-09-16-backtest-contract-first.md)。

### 验收标准

- 回测语义合同四部分全部有可执行 schema
- 三类内核（`event` 可暂缺）输出同一套结果 schema，含 `pit_report` 与
  `diagnostics`
- 与旧 `BacktestEngine` 的行为对照通过，容差显式设定
- `GenericSelectionBacktest` 的去留有明确判定与依据
- 缺价不填充有测试覆盖
- `matrix_id` 的版本敏感性有测试：改一个 `param_hash` 断言 id 变化
- 切分器的 purge/embargo 边界有测试

### 回滚点

回测结果可重算。合同定版后若发现需要修改，走 ADR 流程并重算受影响的结果。

---

## P5 发布与前端

### 内容

1. **冻结输入制品迁入 `frozen/`** 并接上契约校验
2. `publish` 契约与装配器
3. `apps/web` 从旧 `website/` 迁移
4. 文档与制品处置清单执行（清单在 P2 已完成）

### 验收标准

- `tests/contracts/test_frozen_bundles.py` 对所有迁入 bundle 通过：manifest
  完整、digest 一致、行列合同符合
- bond_timing bundle 的 digest 在迁移后仍然校验通过（证明迁移没改内容）
- 每个发布产物携带 `pit_report` 与运行身份
- 前端确实展示 PIT 等级，不折叠进"更多信息"
- 展厅刷新链路端到端跑通，冻结前缀未被重算
- 旧 `website/` 的 schema 校验与 e2e 已迁移并通过

### 回滚点

`publish/` 可重新装配。`frozen/` 迁入前旧仓仍保有原件，迁入后 digest 校验
失败即回退到旧仓版本重新迁移。

---

## P6 旧仓封存

### 前置条件

三份清单中所有「迁入」项已落地，且契约测试通过：

- [../architecture/legacy-inventory.md](../architecture/legacy-inventory.md)
  的提炼/移植项
- [wx2-disposition.md](wx2-disposition.md) 的第一、三、四类
- [docs-and-artifacts-disposition.md](docs-and-artifacts-disposition.md)
  的第一、二、三类

以及：旧调度项逐条对应到新 asset，对应关系记录完成。

### 内容

`pycharm_workspace` 转只读归档。保留 git 历史作为事实追溯来源。

### 验收标准

- 旧仓零写入操作持续一个完整业务周期（含月末、季末、财报季）
- 新系统独立完成一轮完整的月度发布
- 旧调度全部关停，无任务失败告警
- 三份清单中"不迁移"的项都有判定依据与旧仓 commit 指针

### 回滚点

这是最后一个可回滚点。封存后旧仓仍可读，但恢复写入需要重新配置环境
（SQL Server 驱动、Python 3.9 环境），成本较高。因此封存前的验收标准要
严格执行，尤其"持续一个完整业务周期"这条不能压缩。

---

## 贯穿全程的原则

1. **旧仓是权威，直到对拍通过**。任何新旧不一致，先假定新实现有问题。
2. **不在迁移中顺手改口径**。发现旧口径有问题，记 ADR 单独处理，不混在
   迁移里。
3. **每阶段的验收标准是硬门槛**，不通过不进下一阶段。
4. **清单先于执行**。三份清单都是这个模式——先定性，再动手。
5. **golden test 与合同先于实现**。它们定义了什么叫"正确"。

## 进度维护

本文档是活文档，“当前进度”一节是唯一的进度入口，不另建进度台账。每次完成一项或出现新阻塞就更新它。阶段内容需要调整时
直接改本文档；如果调整涉及设计取舍，在 `docs/adr/` 记一份。
