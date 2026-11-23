---
title: 聚源 JYDB 源镜像接入交接
status: active
created: 2026-11-23
updated: 2026-11-23
applies_to:
  - src/quantagent/ingest/sources/jydb/
  - db/migrations/src/
  - src/quantagent/contracts/visibility/
  - src/quantagent/domain/pit/
supersedes: null
superseded_by: null
---

# 聚源 JYDB 源镜像接入交接

本文给接手同步的 agent。先读 `AGENTS.md`、`docs/architecture/layers/ingest.md`、
`docs/domain/pit-rules.md`，再按本文做。数字来自 wx2（旧仓镜像）2026-11-23 的只读查询。

## 目标

- 把下表 P0、P1 的聚源表接成 `src_jydb` 源镜像：首次全量回填，加上每日增量。
  每张表配好可见性契约，并与 wx2 对拍通过。
- P2、P3 在 P0、P1 验收后再做，规则相同。

不做：

- 朝阳永续：规则已定（见下文"写入语义"），但不在本次范围。
- 研究侧读取：`MacroRepository` 登记中国 CPI，由研究线另做。
- 本文"不同步"一节列出的表。

## 旧仓怎么同步

- 脚本 `pycharm_workspace/data/jydb_to_sql.py`，每天 03:30 跑（`task_scheduler/jobs.json`）。
  源库是配置节 `[jy2]` 的 `dbo`，目标是 wx2。
- 整表全量镜像：所有列、所有行，不做行或列过滤。目标主键一律是源端 `ID`。
- 历史初始化和增量都按 `(JSID, ID)` 复合游标分页（`JSID > last OR (JSID = last AND ID > last_id)`）。
  写入时按 `ID` 先删后插，所以源端改过的行会被覆盖；源端物理删除的行不会同步。
- 另有 `run_jydb_jsid_repair`，按 JSID 区间补缺。用于 `Bond_CBYieldCurveAll`、
  `ED_MoneySupply`、`IN_ManufacturingPMI`、`ED_FixedInvestment`。
- 源库本身是订阅子集：`C_ED_IndicatorMain` 只有 92 个宏观指标，89 个有数据。

## 需求表与优先级

| 优先级 | 表 | 用途（旧仓消费者） | wx2 行数 / 大小 | 覆盖 | 建表 | 可见性 |
|---|---|---|---|---|---|---|
| P0 | `C_ED_MacroIndicatorData` | 中国 CPI（`IndicatorCode=110255493`）、PPI、PMI 等；旧仓 11 处 | 114,690 / 8 MB | 1978 – 2026-11 | 0005 已建，PK `ID` | `source_field InfoPublDate`，A |
| P0 | `C_ED_IndicatorMain` | 宏观指标目录 | 92 / 40 KB | — | 0005 已建 | 不配（目录） |
| P1 | `ED_MoneySupply` | M1、M2；旧仓 5 处 | 660 / 0.3 MB | 1952 – 2026-10 | 0005 已建 | 见下文专节 |
| P1 | `C_IN_IndicatorDataV` | 行业指标（伦敦金、地产投资等）；旧仓 7 处 | 367,912 / 28 MB | 1876 – 2026-11 | 0005 已建 | `source_field InfoPublDate`，A |
| P1 | `C_IN_IndicatorMain` | 行业指标目录（负责人 2026-11-23 要求接入） | 213 / 48 KB | — | **未建**，需新迁移 | 不配（目录） |
| P1 | `ED_SocialFinancing` | 社融；旧仓 2 处 | 1,074 / 0.2 MB | 2002 – 2025-12 | 0005 已建 | **待裁定**，见"待裁定" |
| P2 | `CT_SystemConst` | 系统常量 | 172,977 / 17 MB | — | 0005 已建 | 不配（代码表） |
| P2 | `SecuMain` | 证券主表 | 788,079 / 200 MB | — | 0005 已建 | 不配 |
| P2 | `SecuMainAll` | 证券码表总表 | 3,085,554 / 1 GB | — | 0005 已建，**无 PK** | 不配 |
| P3 | `QT_GoldTradeMarket` | 上金所行情；黄金择时 | 127,936 / 42 MB | — | 0005 已建，**无 PK** | `same_day_close TradeDate` |
| P3 | `QT_OSIndexQuote` | 境外、香港指数；大小盘轮动 | 5,830,149 / 1.5 GB | 1896 – 2026-11 | 0005 已建，**无 PK** | `same_day_close TradingDay`（跨时区，见下） |
| P3 | `Bond_BondIndexQuote` | 债券指数；债券择时 | 10,971,808 / 1.7 GB | 1960 – 2026-11 | 0005 已建，**无 PK** | `same_day_close TradingDay` |
| P3 | `DZ_MainOperIncome` | 主营构成；macro_regime 股票池 | 6,277,388 / 2.6 GB | 1998 – 2026-09 | 0005 已建 | 从旧仓 `macro_regime/pools.py` 反推（`InfoPublDate <= as_of`） |

排序理由：

- P0 是研究线（`docs/research/erp-rate-anchor.md`）直接要用的中国 CPI，量很小。
- P1 是其余在用的宏观表，量也小。
- P2 是代码对照表。
- P3 是大表，等 Wind 回填腾出源端带宽再做。

不同步：

- 第二批再评估：`Bond_CBYieldCurveAll`、`ED_FixedInvestment`、`IN_ManufacturingPMI`。
  PMI 已在 `C_ED_MacroIndicatorData` 里，到 2026-10；`IN_ManufacturingPMI` 在 wx2 里停在 2024-08。
- 无消费者，不迁：`Bond_BaseRateReference`、`C_ED_CustomsData`、`CT_Product`、
  `IN_MeansofProductionPI`、`QT_IndexQuote`。

## 写入语义（已裁定）

按 [聚源与朝阳永续源镜像跟随源端](../adr/2026-11-23-jydb-suntime-mirror-follows-source.md)：

- 新键插入。业务字段没变就跳过。业务字段有变化，就在同一事务内按 `ID` 删旧插新，计入 `replaced`。
- 源端没返回的已写行不删。
- 系统列 `JSID`、`UpdateTime`、`XGRQ`、`InsertTime` 变化不算修订。
  每张表的系统列写进写入规格，由测试固定。
- 复用 `ingest/writers/src_follow.py` 的判定逻辑，或按 Wind 分页写入
  （`wind_page.py`、`_batch.source_cursor`）的模式实现分页加游标。不另造写入层。
- 写入保护照旧：双写闸、`tables.py` 白名单、SQL 动词白名单、每页一事务、写后回读、
  事务结果不确定时停止不重试。每次运行落 run log，含 inserted、replaced、skipped 计数。

## 接入步骤

1. **连接配置。** 新仓没有聚源连接。在 `platform/config/settings.py` 加 `jydb_mssql_*`
   （host、port、database、user、password，密码用 `SecretStr`），只放 `.env`，不进 git。
   连接参数向负责人要。旧仓用配置节 `[jy2]`，聚源不在 Wind 那台服务器上
   （当前 Wind 账号看不到其他库）。wx2 只能用 TDS 7.0 握手，聚源源库也可能要显式指定 `tds_version`。
2. **核对列清单。** 采集前把 0005 的列与源端 `INFORMATION_SCHEMA.COLUMNS` 逐表对一遍，
   不一致就停。Wind 有 6 张表因为 0003 与源端不符，在 0019 删表重建过。
3. **补迁移。**
   - 新建 `C_IN_IndicatorMain`。wx2 列：
     `ID bigint NOT NULL`、`IndicatorCode int`、`IndicatorName varchar(300)`、
     `InfoSourceCode int`、`InfoSource varchar(50)`、`PowerNumber int`、`IndiState tinyint`、
     `BeginDate datetime`、`EndDate datetime`、`UnitCode int`、`UnitCodeReport int`、
     `DisclosureFrequency int`、`IndiRemark varchar(1000)`、`UpdateTime datetime`、`JSID bigint`、
     `InsertTime datetime`。以源端为准，PK `ID`，另加 `_batch_id` 索引。
   - P2、P3 的四张无 PK 表（`SecuMainAll`、`QT_OSIndexQuote`、`Bond_BondIndexQuote`、
     `QT_GoldTradeMarket`）：wx2 里 `ID` 唯一且非空，旧仓也以 `ID` 为主键。
     表还是空的，按 0019 的方式删表重建并加 `PRIMARY KEY ("ID")`，在 `migrate.py` 的
     `_REBUILD_PAIRS` 登记。迁移禁止 ALTER。补 PK 前不得启用跟随写入。
   - 每页查询要走索引（`ingest.md`"每页查询的开销不能随表变大"）。如果按 `(JSID, ID)`
     分页，需要补 `(JSID, ID)` 索引。
4. **采集与回填。** 写在 `ingest/sources/jydb/`、`ingest/jobs/`，用 CLI 子命令
   `quantagent ingest jydb <TABLE>`，默认干跑。增量前检查源端 `JSID` 无空值
   （旧仓同样检查）；有些表的 `JSID` 可空。
5. **可见性契约。** 在 `contracts/visibility/src.jydb.*.yaml` 写好，`doc_ref` 指向本文。
   目录类表不配。
6. **可见性引擎。** 两处要补，都在 `domain/pit/`，现在会 fail-closed：
   - **时间戳截止列。** `InfoPublDate` 是 timestamp，`pit_cutoff` 目前只按日期列处理。
     `C_ED_MacroIndicatorData` 有 12,357 行带时刻（比如 CPI 在 09:30 发布）。截止语义待裁定，
     见"待裁定"第 1 条。裁定前不要实现。
   - **`source_field` 加 `fixed_lag` fallback**，供 `ED_MoneySupply` 用。语义是逐行
     `COALESCE(InfoPublDate 的日期, EndDate + 15 天) <= as_of`，可见日来自哪一支要带进返回行，
     用于 `pit_grade`（A 或 B）。不是月末的 `EndDate` 报错。
     其余规则类型仍然 fail-closed。domain 层要有单测，不依赖数据库。
7. **编排。** 新建 Dagster asset 和 schedule（参照 `orchestration/assets/tushare.py`）。
   放哪台机器，取决于哪台能连上聚源，由负责人定。同一来源的自动采集不得在两台机器上同时启用。
8. **进度。** 完成后更新 `docs/migration/roadmap.md` 的"当前进度"。

## ED_MoneySupply 可见性（已裁定）

见 [ADR](../adr/2026-11-23-ed-moneysupply-visibility.md)：

- `InfoPublDate` 非空就用它，等级 A。
- 为空就用 `EndDate` 次月 15 日，等级 B。

注意：2000–2018 年月度行的 `InfoPublDate` 都是回补日，主要是 2019-05-17。
按此规则，这段 M1、M2 要到回补日才可见。与旧仓 `macro_regime` 对拍时会有差异，以 ADR 为准。

## 验收

- 每张表本地行数等于源端 `COUNT(*)`。再按年或按 `ID` 区间与 wx2 比较行数和 digest，
  差异逐项解释：源端修订（`JSID` 更新）、订阅范围不同，或 wx2 同步缺口。
  做法参照 `tests/golden/test_erp_inputs_wx2_golden.py`。
- golden：`C_ED_MacroIndicatorData` 指标 `110255493`（CPI 当期同比）2007 年以后
  每期的 `EndDate`、`InfoPublDate`、`DataValue` 与 wx2 一致。
  wx2：478 期，2007-01 起有发布日，1987–2006 年 240 期发布日为空、按规则不可见。
- 可见性契约齐全，`quantagent check contracts` 通过。
- ruff、mypy、import-linter、pytest 全部通过。新写入路径对六条写入保护各有测试。
- 增量连跑两次，第二次 inserted 和 replaced 都为 0。

## 待裁定（遇到就停下问负责人）

1. **`InfoPublDate` 带时刻时，发布当天算不算可见？**
   - pit-rules 写的是 `InfoPublDate <= as_of`。
   - 旧仓实际传 `'YYYYMMDD'` 给 SQL Server 比较 datetime，日期按 0 点算，
     所以 09:30 发布的数据要到次日才可见。
   - 金十中国 CPI 与 Wind `ANN_DT` 的口径都是"含当日"。
2. **`ED_SocialFinancing` 没有发布日字段。** 列里没有 `InfoPublDate`，pit-rules"聚源宏观用
   InfoPublDate"对它不成立；旧仓消费者只做覆盖探查，没有给出可见日规则。
   另外，wx2 中该表停在 2025-12，最后更新 2026-01-16，要查清是源端停更还是同步中断。
3. **`QT_OSIndexQuote` 的跨时区问题。** 美股指数 `TradingDay` 当日的收盘晚于北京时间同日。
   做法参照 `src.tushare.us_treasury_yield`：契约写 `same_day_close`，更严的截止由调用方的
   `as_of` 表达。写进 rationale。
4. **`pit_recoverable` 怎么填。** Wind 财报契约写的是 `true`，但源镜像是原地修订
   （wx2 里每个 `(IndicatorCode, EndDate)` 只有一行，没有版本史）。聚源先与 Wind 保持一致，
   这个不一致单独提给负责人。
