---
title: 公开宏观源与 Tushare 采集方案（已评审）
status: active
created: 2026-11-18
updated: 2026-11-18
applies_to:
  - src/quantagent/ingest/
  - db/migrations/src/
  - orchestration/
---

# 公开宏观源与 Tushare 采集方案

**已评审，裁定结果见文末。分表原则待负责人确认。** 为宏观、债券、黄金、美股择时及风格轮动补齐公开源和 Tushare
的存量采集与每日增量。债券四票的聚源和 Wind 数据仍走供应商同步链路。本方案覆盖数据接入，策略接线另行验证。

## 部署与写入

公司电脑运行 Wind、聚源、朝阳永续源表同步，沿用该 Dagster 实例的全局串行。Mac mini 运行公开源和
Tushare 日更，使用独立的 `DAGSTER_HOME`、SQLite 和队列。见
[Dagster 本地运行存储](../adr/2026-11-17-dagster-local-run-storage.md)。

**写入入口按 schema 划分，并在代码里强制。** 公司电脑只写 `src_wind`、`src_jydb`、`src_suntime`；
Mac 只写 `src_tushare`、`src_macro`。两边各有自己的 `_batch`，游标互不相干。两台机器跑同一份代码，
目标白名单分不出机器，所以按 `QUANTAGENT_PROFILE`（`office` / `local`）限定可写 schema，
写入前在 `assert_writable` 里拒绝不属于本机的目标（已实现，`PROFILE_WRITABLE_SCHEMAS`）。

Mac 直连本机 PG，不经过 ToDesk，前一轮的链路问题在这里不存在。但 PG 数据目录和 `var/` 都在外接盘
`/Volumes/QuantDB` 上：Mac 的 daemon 要在外接盘挂载之后才启动，启动脚本先检查挂载点，未挂载即退出。
Mac 写库用 `quantagent_ingest`，不用超级用户 `leo`；日更需要 Mac 的 `.env` 打开 `QUANTAGENT_ALLOW_DB_WRITE`。
`QUANTAGENT_TUSHARE_TOKEN` 与 `QUANTAGENT_FRED_API_KEY` 已在 `.env.example` 里。

CLI 回填和 Dagster 日更调用同一个 `ingest` 作业，复用 PostgreSQL 适配器和 `src_<source>._batch`。
回填显式指定区间并分批提交，日更从最近成功位置重查一段。批次登记、数据写入与行数和 digest 回读在同一事务内完成，
成功提交才推进水位。沿用双写闸与目标白名单，提交状态未知时停下核对。每源独立报告成功、无更新、
预期数据未到或失败。公开源日更按自然日检查，具体时点以源端发布时间和试跑为准。见
[采集层约束](../architecture/layers/ingest.md)。

**修订怎么处理，按源是否自带版本分两类：**

- **源端给出版本身份**（ALFRED 的 `realtime_start`、WGC 报告期次、GPR 文件摘要、金十事件身份）：
  修订按新版本追加，旧版本不动。这是源端发布的事实，不是我们自己的采集批次快照，见
  [源端发布的版本可以落表](../adr/2026-11-18-source-published-versions.md)。
- **源端不给版本**（Tushare `shibor`、`us_tycr`）：全自动跟随源端，业务字段变了就按主键删旧插新，不要人工介入（[ADR](../adr/2026-11-18-tushare-mirror-follows-source.md)）。

| 数据源 | 目标表 | 存量 | 日更 |
|---|---|---|---|
| Tushare `shibor`、`us_tycr` | `src_tushare.shibor`、`src_tushare.us_treasury_yield`（已建，长表） | 按日期分段拉取，与 `wx2` 校对期限、精度和空值 | 重查近期区间，追加新日期，缺期单独报告 |
| FRED／ALFRED `DFII10`、`T10YIE`、`CPIAUCSL` | `src_macro.macro_fred_observation` + 新增版本表 | 按序列补齐研究期和预热期，取全部官方历史版本 | 按 `realtime_start` 发现新增和对旧观测的修订 |
| 金十美国 ISM PMI | `src_macro.macro_jin10_usa_ism_pmi`（需补 `period_end`） | 对账历史接口与日历详情的交接期，保留统计期和源事件身份 | 发现新发布，复查近期事件的修订 |
| GPR `gprd_act` | `src_macro.macro_gpr_daily` | 下载历史序列，核实可证实的文件版本 | 检查文件摘要，逐次登记可证实的版本 |
| WGC `WORLD/BARS` | `src_macro.macro_wgc_gold_demand` | 主报告归档匹配季度、发布日期和对应数值 | 检查主报告目录，按报告版本追加 |

## 源表结构

- **Tushare 保留现有长表。** `shibor` 与 `us_treasury_yield` 已按 `(trade_date, maturity)` 建成长表，
  主键合适，表是空的。API 返回宽表，入库时逐期限展开，这一步只换形不改值，逐期限一行与源端一一对应。
  原方案提议改成宽表，需要删表重建并在门禁里登记历史例外，收益只是少一次展开，不值得。
- **FRED 现表只能存一个值。** 主键是 `(series_id, observation_date)`。新增窄表
  `macro_fred_vintage(series_id, observation_date, realtime_start, value)`，主键含 `realtime_start`，只用 CREATE。
  现表是否保留为“最新值”，实施时定；保留的话它只是派生，不作 PIT 依据。
- **金十现表缺统计期。** 只有 `publish_date`，主键是 `record_hash`。补 `period_end` 要新建表（禁 ALTER），
  实施前先核对接口里统计期从哪个字段来。

## 分表原则（待确认）

旧仓口径不一：金十每个指标一张表（`macro_jin10_usa_ism_pmi`、`_china_cpi_yoy`、`_china_ppi_yoy`，列完全相同），
FRED 按 `series_id` 一张长表，SHIBOR 与美债按期限一张长表，GPR 单指标单表。新仓源层统一为：

1. **按源端数据产品分表，不按指标分表。** 一个接口或一类文件一张表：金十经济日历一张、FRED 观测一张加版本一张、
   GPR 一张、WGC 一张、Tushare 每个接口一张。新增指标只加行，不加表、不改 DDL。
2. **同一产品内，同质度量用长表。** 只差一个维度（指标、期限、地区）的数值，用“维度列 + 值”，维度列进主键：
   `(indicator, period_end, 版本)`、`(trade_date, maturity)`。
3. **异质字段保持源端列。** 一条记录里含义不同的字段（实际值、预期值、前值、单位）照源端分列，不压成键值对。
4. **按指标的取用在 std / mart 层做。** 研究要“ISM 序列”就在 std 层按 `indicator` 筛，源层不为某个指标单独建表。
5. **可见性按数据集配。** 同一张表里各指标发布时点不同（ISM 美东 10:00、中国 CPI 北京 09:30），
   靠带时区的发布时刻统一判断（裁定 3），不再为可见性拆表。旧仓按指标拆表，部分正是因为日期规则只能整表一条。

分表原则 2026-11-18 已确认。已建空表中 `shibor`、`us_treasury_yield`、`macro_wgc_gold_demand` 保留；
另外三张按下面的设计新建，旧空表按 0012–0016 先例登记为历史删表。设计依据是旧仓采集代码与 wx2 实测（2026-11-18）。

| 新表 | 主键 | 其余列 | 依据 |
|---|---|---|---|
| `src_macro.jin10_economic_calendar` | `(indicator_id, publish_date, data_id)` | `period_end`、`time_period`、`published_at timestamptz`、`actual_value`、`forecast_value`、`previous_value`、`revised_value`、`source` | `indicator_id` 用金十 `datanameId`（ISM 129）。详情接口给 `pub_time`（UTC）与 `dataId`；历史列表只有日期，`data_id` 记 0、`published_at` 为 NULL，可见性回退为严格 `< as_of` |
| `src_macro.gpr_daily` | `(series_id, observation_date, file_vintage)` | `value`、`file_sha256`、`source` | 文件列 `GPRD`、`GPRD_ACT`、`GPRD_THREAT` 等按 `series_id` 成行。文件没有版本字段，`file_vintage` 取文件里最大的 `DAY`，与旧仓 `gold_timing/pit.py` 一致，等级不高于 C |
| `src_macro.fred_observation_vintage` | `(series_id, observation_date, realtime_start)` | `realtime_end`、`value`、`source` | 用 ALFRED 的 `realtime_start/realtime_end` 取全部版本；源端 `"."` 记 NULL 并保留该行 |

旧 `macro_fred_observation` 不再新写：当前值由版本表取 `realtime_end` 为最新的一版得到，在 std 层算。

## PIT

每个数据集先写 visibility YAML 和 schema 契约，再接读取，缺规则即 fail-closed。规则来源：

| 数据集 | 规则 | 等级与可恢复性 |
|---|---|---|
| Tushare `shibor`、`us_tycr` | `same_day_close`，`trade_date` | A |
| FRED／ALFRED | `source_field`，首个 `realtime_start`，严格 `< as_of`（[pit-rules](../domain/pit-rules.md)） | A；ALFRED 有完整历史版本 |
| 金十 ISM | 带时区的发布时刻，按消费市场收盘判断（裁定 3） | 接入前扩展规则引擎；扩展前维持 `< as_of` |
| GPR、WGC | 有可证实发布日期的版本用该日期 | 缺证据的历史段 `pit_recoverable: false` 并给 `pit_from`，等级不高于 C |

`_ingested_at` 只作采集记录，不作可见日。

## 实施与验收

**进度（2026-11-18）**：写入入口按 profile 强制已上线。SHIBOR 端到端完成：本机全量回填 2006-10-08 至 2026-11-17
共 40,008 行，与 wx2 `macro_shibor` 键与值逐一相同；同窗重跑零新增；19:00 日更调度已注册（仅 Mac）。
0018 已在本机执行，三张新表与契约就绪（金十 B、FRED A、GPR C，三者均严格早于 `as_of`）。美债 `us_tycr` 完成：全量 1990-01-02 至 2026-11-17 共 99,656 行，与 wx2 逐值一致，并入 `tushare_daily`。金十没有可用的事件发现接口：`list_v2` 停在 2025-09-02，财经日历 CDN 在 Mac 上 TLS 断开（DNS 落在本机代理 fake-IP 段），详情接口须已知 `dataId`。

1. 先做写入入口按 profile 强制，以及 Mac daemon 的挂载检查。
2. 用 SHIBOR 验证端到端：存量与 `wx2` 校对、同窗重跑新增零行、中断后从成功批次续跑、下一次真实发布自动追加并通过回读。
3. 依次接美债、FRED、金十、GPR、WGC，每个先过契约与 PIT，再逐源核对覆盖、缺口和旧仓差异。
4. 两台机器同时运行一次，验证队列独立、各自只写本机允许的 schema。
5. 每次写库运行都落 run log；新增依赖（如解析 xlsx 需要 `openpyxl`）实施前单独确认，现有依赖只有 `requests` 与 `tushare`。

## 裁定结果（2026-11-18）

1. **写入入口按 profile 强制**：采纳，已实现。公司电脑须设 `QUANTAGENT_PROFILE=office`，否则写 Wind 会被拒绝。
2. **Tushare 已有键异值**：全自动跟随源端，见 [ADR](../adr/2026-11-18-tushare-mirror-follows-source.md)。
3. **ISM 可见性按时区**：采纳。源表保存带时区的发布时刻，可见性按消费市场的收盘时刻判断，接入金十前扩展规则引擎。
   扩展前维持 `< T`。
4. **源端版本落表**：确认，见 [ADR](../adr/2026-11-18-source-published-versions.md)。
