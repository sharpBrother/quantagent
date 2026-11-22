---
title: 迁移路线 P0–P6
status: active
created: 2026-09-16
updated: 2026-11-21
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

## 当前进度 · 2026-11-19（晚）

**本节是项目唯一的进度入口（pipeline）。** 每完成一项就改这里：勾掉、补日期与提交号，新出现的阻塞写进
“阻塞与待裁定”。细节与证据放在下面链接的专题文档里，本节只写结论。各表实时行数用
`uv run quantagent ingest progress` 看（全部源 schema）。

### 阶段总状态

| 阶段 | 状态 | 一句话 |
|---|---|---|
| P0 骨架 | ✅ 完成 | 门禁 ruff / mypy / import-linter / pytest 全绿 |
| P1 存储底座 | ✅ 完成 | 两面迁移、DuckDB 会话、缺规则 fail-closed、因子布局 ADR |
| P2 处置与入湖 | 🔄 进行中 | Wind 回填中；Tushare 两表与宏观两源已日更；JYDB、朝阳永续未接 |
| P3 口径与因子 | 🔄 提前起步 | 股票池与 ST 读取已实现并对拍 wx2；等数据进库做真实库验收 |
| P4–P6 | ⏳ 未开始 | |

### 运行环境

| 机器 | profile | 调度 | 托管 | 状态 |
|---|---|---|---|---|
| 公司电脑 | `office` | Wind 16:30、06:00（交接期间暂停） | Windows 计划任务 | 经 ToDesk 连 PG |
| Mac mini | `local` | Tushare 19:00、宏观 08:00 | launchd `com.quantagent.dagster-daemon` | Wind 回填交接中 |

2026-11-21 负责人取消按机器划分源的写入职责；目标表白名单及写库保护保留。
两机队列独立，同一来源的自动采集不得跨机同时启用。

Dagster 运行存储都是各机本地 SQLite（[ADR](../adr/2026-11-17-dagster-local-run-storage.md)）。
采集在子进程里跑，600 秒无新页即终止重试。

### P2 数据入湖明细

**Wind（第一批 30 张全部已接，另加 `AINDEXDESCRIPTIONZL`；Mac 接手回填）**：首次回填走独立作业 `orchestration/jobs/wind_initial.py`，按下表优先级串行（`c9db3c3`）；日更顺序不变。

| 优先级 | 表 | 状态 |
|---|---|---|
| 1 | `ASHAREST` | ✅ 3,358 行，与 wx2 一致（11-19） |
| 2 | `ASHAREEODDERIVATIVEINDICATOR` | ✅ 28,449,317 行（11-22）；0024 补 `TRADE_DT` 索引，单日读取 20 秒降到 0.2 秒。源表含周末行（2018 年以来 1,086 个非交易日），按日计数须先按交易日历过滤 |
| 3 | `ASHAREDESCRIPTION`、`ASHAREEODPRICES`、`ASHARECALENDAR`、`AINDEXEODPRICES` | ✅ 已追平。描述表 8,621 行对 wx2 8,635 行，差 14 行待核 |
| 3 | `AINDEXMEMBERS`、中信一二三级成分 | ✅；`SWINDEXMEMBERS` 🔄 |
| 4 | 利润表、资产负债表、现金流量表、财务指标、业绩预告 | ⏳ 未回填 |
| 4 | `ASHAREDIVIDEND` | 🔄 约 15.7 万 / wx2 16 万 |
| 5 | 指数估值、中信行业行情、两融明细、两融汇总、停牌 | 🔄 部分；两融明细仅 5 万行 |
| 6 | `ASHAREMONEYFLOW` | 🔄 461 万 / 1,328 万，无新仓消费者 |
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

**A 股 1 分钟行情**：⏸ 回填停止（11-22）。MySQL 只用于历史回填，后续使用东财；PG 已执行 `0023_minprice_manifest.sql`。负责人裁定开盘价低于最低价不超过最低价的 0.5% 时保留原值并记录；2024-07-29 源表为空；2025-10-17 有 45 条负成交额，负责人决定暂时跳过。2025-10-28、2025-11-26 和 2025-12-08 的各一条负值已按负责人要求修正为 0，整日入库并校验，分别见 [10 月修正 ADR](../adr/2026-11-21-minute-bar-negative-correction.md)、[11 月修正 ADR](../adr/2026-11-21-minute-bar-november-negative-correction.md) 和 [12 月修正 ADR](../adr/2026-11-22-minute-bar-december-negative-correction.md)。已登记 332 个分区、414235180 行，连续历史至 2025-12-10；2025-12-11 因负成交额停止，当日未入库，日志在 `var/logs/minprice-backfill-5a94ebc91b.log`。源数据含三板做市指数，股票与指数范围需另行裁定。东财全市场在线验证未完成，日更调度默认停止。见 [来源 ADR](../adr/2026-11-21-minute-bars-source-split.md) 与 [接入方案](minute-bar-ingest-plan.md)。

**其他**：JYDB 12 张、朝阳永续 7 张、Tushare 其余接口 ⏳ 未接（JYDB、朝阳在公司电脑上）；第四类运维表 ⏳ 未动。

### P3 口径与因子

| 项 | 状态 | 前提 |
|---|---|---|
| `all_a` 股票池（读取时计算） | ✅ 真实库 2,145 个金样本日：2,138 天与 wx2 一致，7 个已知例外日按预期不同（11-22，测试只读 PG） | — |
| 指数 / 行业成分池 | ✅ 真实库 4 宽基 × 85 月末与 wx2 一致（11-20）；申万表负责人已核验（11-22） | — |
| ST 状态 | ✅ 真实库 202 个月末与 wx2 一致（11-20） | — |
| cutamp、tr_umr | 🔄 小样本入长表，与 wx2 一致 | 2024-01-05 全截面 golden 可以开始（`all_a` 当日 4,860 只与 wx2 一致） |
| 其余网关 golden、`pit_grade` 木桶测试 | ⏳ | 不依赖数据，可随时做 |
| `alpha_factory` 因子批量移植 | ⏳ | 量价等全截面 golden；基本面等四张财报表 |

### 下一步（按顺序）

1. ~~真实库跑 `all_a`、成分池、ST 集成测试~~（11-22 完成）。
2. 2024-01-05 全截面固化 cutamp、tr_umr 对 wx2 的 golden。
3. P3 其余 golden 与 `pit_grade` 木桶测试（可与 1 并行）。
4. 量价因子批量移植；财报表回填后移植基本面因子。

### 阻塞与待裁定

| 事项 | 等谁 |
|---|---|
| ISM、美债等跨时区数据的可见性：按消费市场收盘时刻判断，需扩展规则引擎 | 已裁定，待实现 |
| ToDesk 链路会吞连接：回填靠看门狗与逐列回读兜底，未根治 | 观察 |
| wind_db 列注释复核：2026-11-20 导出 `MS_Description` 25,409 条，对完 23 张表 1,118 列；43 列补说明、119 列正文与单位改用 wind_db，`0022` 已生成待执行 | 已结案 |
| daemon 连 PG 用超级用户 `leo`，应改 `quantagent_ingest` | 负责人放密码 |

专题文档：[Wind 交接](wind-pipeline-handoff.md)、[宏观采集方案](macro-source-ingest-plan.md)、
[wx2 清单](wx2-table-list.md)、[ADR 索引](../adr/README.md)。

---|---|
| P0 | 完成。门禁 ruff、mypy、import-linter、pytest 全绿 |
| P1 | 完成。两面迁移可独立 migrate/status，DuckDB 会话、缺规则 fail-closed 测试、因子布局 ADR 均已落地 |
| P2 | 进行中。两份清单完成。第一批 59 张源表 DDL 已建；Wind 30 张里 25 张已接分页采集，有数据的 4 张（日历、A 股日行情、指数日行情全量，资金流 9 万行）。剩 5 张无主键表、`AINDEXINDUSTRIESCITICS`、`CBONDCURVECNBD` 待定。Tushare 除日历外、JYDB、朝阳永续、宏观未接。源表 visibility 只写了 4 张。第四类运维表未动 |
| P3 | 提前起步。domain 的 calendar/pit/universe/prices、8 个 port、三套适配器已有；golden 只覆盖日行情与 cutamp；两个量价因子小样本入长表 |
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
