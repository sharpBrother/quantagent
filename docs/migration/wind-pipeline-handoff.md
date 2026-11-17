---
title: Wind 数据链路迁移交接
status: active
created: 2026-11-15
updated: 2026-11-17
applies_to:
  - orchestration/
  - src/quantagent/ingest/jobs/wind_paged.py
  - src/quantagent/lake/materialize/trade_calendar.py
  - src/quantagent/domain/ports/
---

# Wind 数据链路迁移交接

## 当前状态 · 2026-11-17

| 项目 | 已验证 | 待完成 |
|---|---|---|
| PostgreSQL | 本地研究库和控制库可连通。研究库迁移已应用到 `0011_src_batch_id_indexes.sql`，控制库到 `0002_dagster_storage.sql`，待应用均为 0。五个源 schema 的现有表和序列已授权，`leo` 新建对象会自动授权给 `quantagent_ingest`。项目环境已安装 Dagster 和 pymssql。本机未配置 Wind 源库。只读 `wx2` 可用。`ops` 有 21 张 Dagster 运行表，`public` 里没有。 | 确认 Dagster 执行端能同时访问 Wind、目标 PG 与物化目录。本机没有 Wind。 |
| Wind 日历 | `ASHARECALENDAR` 已初始化，31,483 条开市记录、5 个市场代码。提交 `f9abaf3` 已将 `scan_trade_cal()` 和标准日历上游切到 Wind。`quantagent lake materialize trade-calendar --as-of 2026-11-15` 写入正式分区 47,389 行，digest `b6d8463d8b7e29b0a9bcc08cc54f8a11e37ac85da68b397a33259968e64d0e9c`。SSE 上 2026-11-13 开市、14 与 15 日闭市，上一交易日是 13 日；`as_of=2026-11-15` 读不到 11-16。 | 正式分区已可读。后续由 `std_trade_calendar` 资产重跑，不覆盖既有文件，除非显式 rebuild。 |
| Wind 日行情 | `ASHAREEODPRICES` 18,870,269 行，8,768 个交易日，1990-12-19 至 2026-11-13。与 `wx2` 的交易日集合相同。`wx2` 多 290,194 行，每个交易日的行数差都等于 `.BJ` 行数差。`wx2` 的北交所行情从 2008-02-21 起共 575,350 行，本机从 2020-07-27 起共 285,156 行。行数不同的 3,918 个交易日止于 2024-04-03，之后每天行数相同。2026-11-13 两边都是 5,579 行，开高低收、成交量、成交额、涨跌幅、涨跌停和复权收盘价逐行相同。非北交所代码的 10 个行情字段已按全部 8,768 个交易日核对。1990–2013 与 2025–2026 共 6,358 个交易日完全相同。2014–2024 有 2,410 个交易日至少有一行不同，代码集合没有差别。开高低收、成交量、成交额和涨跌幅也没有不同。2026-11-17 补核北交所：两边都有的 284,398 行里，284,386 行十个字段相同。 | 本机没有 Wind，未做游标后的下一页真写。`wx2` 游标后有 10,463 行；其中 4,884 行复权列有修订，会自动替换，不再停下（源镜像全自动跟随源端）。 |
| 编排与研究 | 三个资产已接入。日行情按 `as_of` 读取。`pf_single_cutamp_1_mean_neg` 已有两个月份分区：2024-01 的 8 行，以及 2024-02-01 至 02-08 两只样本股票的 12 行，digest `0782d593624e581f786ed87a95545bdf3e4ebe06051341dddf11e5824e774c53`。1 月文件未被 2 月写入改动。同范围再写会被拒绝。`knowledge_dt` 等于截面日，行级 `pit_grade` 为 A。12 行里 11 行四舍五入到 6 位后与 `wx2.stock_cutamp` 的相反数一致。不一致的是 2024-02-02 的 `000001.SZ`，行情与 `wx2` 相同，差异仍是复权收盘价并列时的排序。实例模板 `orchestration/dagster.yaml` 已复制到 `QUANTAGENT_VAR_ROOT/dagster`。2024-03-01 至 03-08 的 `000001.SZ` 与 `600000.SH` 经该实例物化 12 行，digest `48a739baa14c14c37cfe440361ed75adf0bf4ecd0c35fc6a68c82d1358e2cd09`。12 行都与 `wx2.stock_cutamp` 的相反数在 6 位小数上一致。运行 `3c1269ed-71c2-4d6f-a16e-92f22ed84a8c` 在 `ops.runs` 中为 `SUCCESS`，`event_logs` 12 行。1 月和 2 月分区未改。表仍是 21 张。 | 启动 Dagster 时把 `DAGSTER_HOME` 指到 `QUANTAGENT_VAR_ROOT/dagster`。旧仓日更尚未切换。 |

## 下一轮实施与验收

1. **真实源烟测已结束，运行存储已接到控制库。** 2026-11-15 在 `8590e16` 上，
   日历与日行情干跑都是 `pages=0`，未真写。取数条件是 `OPDATE` 更大，或同一
   `OPDATE` 下 `OBJECT_ID` 更大；起点游标探针能取到历史行，所以这是游标后无行。
   `_batch` 按 `_batch_id DESC LIMIT 20` 会只看到日历，因为日历批次号更新。
   看某张表要用该 dataset 自己的最大成功批次。下一次真写等到游标之后有新行再做，
   仍必须带 `--max-pages 1`。Dagster 运行表进控制库 `ops`，不进研究库。
   表形写在 `db/migrations/ops/0002_dagster_storage.sql`，只含 `CREATE`。
   实例模板关闭自建表，并已复制到 `QUANTAGENT_VAR_ROOT/dagster`。用它物化 2024-03-01 至 03-08 两只样本股票，12 行与 `wx2` 在 6 位小数上一致。`ops.runs` 记下一次 `SUCCESS`。
   写库沿用双闸。失败日志保留已提交页；提交结果未知的页不计入、不自动重试。
2. **指数日行情已落地，2026-11-16 完成全量初始化。** `src_wind.AINDEXEODPRICES` 物理表
   已按源表重建为 22 列，2026-11-17 核对全表 24,598,322 行；`000985.CSI` 5311 行，
   `TRADE_DT` 从 20041231 到 20261116。2026-11-16 23:49 收尾，3,222 个批次全 `success`，
   `TRADE_DT` 覆盖 19901219–20261116 共 9,297 个交易日、6,947 个指数；孤儿行 0、
   (代码, 交易日) 重复 0；干跑 `pages=0` 已追平，最新成功游标 `opdate` 为
   2026-11-16T21:26:24。采集命令仍是 `quantagent ingest wind AINDEXEODPRICES`，游标与
   A 股日行情相同。采集列和物理表都只跟 `wind_db.dbo.AINDEXEODPRICES`，另加三个系统列。
   `0009_aindexeodprices_source_columns.sql` 在表为空时删掉重建，去掉 19 个简介列。
   本机没有 Wind。初始化要在能连源库的机器上做：先干跑一页，再开写闸。
   真写默认不限页。可见性是 `TRADE_DT` 的 `same_day_close` / A。
   分页用 `--page-size 10000`（`_MAX_PAGE` 的上限），比默认 1000 快约一倍：
   1000 行/页实测 1.6 秒/页、约 620 行/秒；10000 行/页 7.8 秒/页、约 1,180 行/秒。
   单次取数开销随行数一起涨，省掉的只是固定开销，所以再往上没有空间。
   全量 2,459 万行按 10k/页估 5.4 小时，实际约 8.5 小时，其中约 4 小时是断链停机。
   扣除停机仍偏慢：回读校验按 `_batch_id` 过滤，而该列只有外键、没有索引，
   每写一页做一次全表顺序扫描，吞吐从 1,440 行/秒掉到 508，开销随表增长。
   已改为按本页主键回读，并新增 `0011_src_batch_id_indexes.sql` 给 60 张源表的
   `_batch_id` 建索引，设计要点见 `docs/architecture/layers/ingest.md`。
   0011 已于 2026-11-17 在本机库执行，用时 32 秒，60 个索引全部有效。
   `AINDEXEODPRICES` 的索引 163 MB，`ASHAREEODPRICES` 的 125 MB。
   按批次查一页 2,322 行走该索引，耗时 0.9 毫秒。
   每页一事务（批次登记、插入、回读、提交同一事务，游标随提交推进），
   中途中断最多丢当前页，续跑从 `latest_source_cursor` 重读，不留孤儿行。
   `S_DQ_OPEN` 有 1,708 万行为空（69%），是源端原生：`h21006.CSI`、`932144.CSI`
   这类指数只给收盘，OHLC 其余为空，按不填充原则保留 `NULL`。2026-11-16 当日
   5,889 只少于前一交易日的 6,731，是源端当晚尚未加载完，下次刷新从游标续抓即可。
   `pf_single_tr_umr_1_mean_pos` 已按旧仓 `TR_UMR` 重算，消费窗口为 1、方向 +1。
   2024-01-02 至 01-05 的 `000001.SZ` 与 `600000.SH` 共 8 行已写入
   `asset_class=stock/ym=202401/part-00001.parquet`，文件 sha256
   `1a724e13e9740b4259de1962cf94530ad6068d71ce0f3ef9d945772ea745c55b`，
   行 digest `3fc0bf560d94ae207f152c9079ec08a2d8f7c1e3fc88d8525f3722f12179d3d0`。
   同目录里原有的 4 个 parquet 未改。同一范围再写被拒绝。8 行四舍五入到 8 位小数后与
   `wx2.dbo.stock_tr_umr.tr_umr` 一致。`knowledge_dt` 等于截面日，`pit_grade` 为 A。
   2024-01-05 当天 `wx2` 有值的 4861 只全部算出。其中 4858 只在 8 位小数上一致。
   不一致的 3 只输入不同：`000717.SZ` 与 `000016.SZ` 的复权价有 0.0001 的差别，涨跌幅相同；
   `000078.SZ` 的复权价是常数比例，真实波幅里这个比例会消掉，因子只剩 7e-9。
   这 4861 行没有写入长表。2024-02-01 至 02-08 的 6 个开市日、同样两只股票共 12 行
   已写入 `asset_class=stock/ym=202402/part-00001.parquet`，文件 sha256
   `387dc05b9f095664b21ad9863825107dae6c5b7eb32803d710d818cc26b00f21`，
   行 digest `2a57c3516b526ba09541d8d6220f0cff30ed139540b79138ee790ccdc0955693`。
   12 行在 8 位小数上与 `wx2` 一致。2 月原有 parquet 未改，同一范围再写被拒绝。
   2024-03-01 至 03-08 的 6 个开市日、同样两只股票共 12 行已写入
   `asset_class=stock/ym=202403/part-00002.parquet`，文件 sha256
   `8e46edf195e73665ac473d4163a1074cc77072e507e8e923f5e5bfd8ef05c4f7`，
   行 digest `836ead683163f55b2f50e1403a0b2b8ae192343a2814f5f648ac9468e162d994`。
   12 行在 8 位小数上与 `wx2` 一致，`knowledge_dt` 等于截面日，`pit_grade` 为 A。
   3 月原有 parquet 未改，同一范围再写被拒绝。
   2024-03-11 的同样两只股票经 `DAGSTER_HOME` 物化 2 行，digest
   `b6dbf2fd8a03cc48099b109f167b1acbd300a76578f7ab8c2c9eedfdfbcc9459`，
   追加为 `asset_class=stock/ym=202403/part-00003.parquet`，文件 sha256
   `f997943adbac24a086378536f81f2597dca57b2497ace5616d7979d68ea6c8d2`。
   2 行在 8 位小数上与 `wx2` 一致。03-01 至 03-08 的 part 文件 sha256 未变。
   运行 `81da3817-4ad2-4c4e-bd42-ab06e9807fd5` 在 `ops.runs` 中为 `SUCCESS`，
   `event_logs` 12 行。`ops` 仍是 21 张表。
   旧表 `stock_tr_umr` 不迁，旧入口不切。
3. **达到 3GB 的源表按体积从大到小采集。** 命令是 `quantagent ingest wind large`。
   顺序：`ASHAREMONEYFLOW` 32GB、`ASHAREEODDERIVATIVEINDICATOR` 19GB、
   `ASHAREEODPRICES` 15GB、`ASHARECASHFLOW` 6.4GB、`ASHAREINCOME` 5.8GB、
   `ASHAREBALANCESHEET` 3.7GB、`AINDEXVALUATION` 3GB。
   默认每张干跑 1 页，页大小 10000。真写要开写闸，并且不要传 `--max-pages`。
   页大小用指数全量测到的上限：10000 行/页约 1,180 行/秒，默认 1000 只有约 620。
   `_batch_id` 索引已在 `0011_src_batch_id_indexes.sql` 落地，回读不再扫全表。
   开跑前用 `wind_db` 的列清单对采集列，不一致就停。
   `ASHAREMONEYFLOW` 是空表，已去掉源端没有的 `GSUPDTIME`。
   `ASHAREEODPRICES` 已有数据，`GSUPDTIME` 仍留在物理表里、不采集。
   截图里的 `Bond_CBYieldCurveAll` 不在第一批源表，这次不接。本机不跑这批数据。
   2026-11-17 本机仍没有 Wind，游标仍是 `2026-11-13T15:09:05` / `7700421104`。
   `wx2` 在这个游标之后有 10,463 行，最大 `OPDATE` 为 2026-11-16 15:17:23。
   其中 5,579 行是新交易日 20261116，含 355 行 `.BJ`。
   另外 4,884 行是 `603273.SH`（743 行，20231023–20261113）、
   `601881.SH`（2,380 行，20170123–20261113）、
   `688188.SH`（1,761 行，20190808–20261113）的 `OPMODE=1`。
   这 4,884 个 `OBJECT_ID` 本机都有。早先只比了十个行情字段，结论“只变了 `OPDATE`”不对：
   2026-11-17 逐列比对全部业务字段，4,884 行都在复权列上有变化，主要是
   `S_DQ_ADJCLOSE_BACKWARD`（后复权收盘），例如 `601881.SH` 20210305 由 9.3488 改为 9.2272。
   写入规则已改为自动跟随（[ADR](../adr/2026-11-17-wind-revision-auto-replace.md)）：
   只变系统列的跳过，只变复权列的自动替换，其余变化仍拒绝。用 wx2 游标后的 10,463 行
   只读推演：新增 5,579、自动替换 4,884、无报错。本机没有 Wind，未真写。
   **第一批其余 15 张常规 Wind 表已接入分页采集（2026-11-17，未真写）。** 命令
   `quantagent ingest wind first-batch`，也可单表 `quantagent ingest wind <表名>`。顺序：
   `ASHAREDESCRIPTION`、四张成分表、`SWINDEXMEMBERS`、`ASHAREFINANCIALINDICATOR`、
   `ASHAREPROFITNOTICE`、`ASHAREDIVIDEND`、`ASHAREST`、`ASHARETRADINGSUSPENSION`、
   `AINDEXINDUSTRIESEODCITICS`、两张两融、`CHINAMUTUALFUNDSTOCKPORTFOLIO`。全表镜像，
   不沿用旧仓按指数清单或 `CUR_SIGN=1` 的子集过滤，与指数日行情一致。采集列取本机物理表，
   测试核对与已应用 DDL 一致；中文解码列按旧仓 `chi_field`。默认干跑一页，页大小 10000。
   未接的 7 张：`CBONDCURVECSI`、`FXEODPRICES`、`CBONDREPO`、`CBONDPRICESREPO`、
   `CBONDREPOANDIBLEODPRICES` 的物理表没有主键；`AINDEXINDUSTRIESCITICS` 在旧仓由
   `AINDEXDESCRIPTION` 筛出，源表不同名；`CBONDCURVECNBD` 全表体量未评估。
4. **首个量价因子已对上一个小样本。** `pf_single_cutamp_1_mean_neg` 来自旧仓
   `CUTAMP`：20 个交易日的振幅，去掉收盘触及涨跌停的日子，按复权收盘价切 25%。
   Current-20 取相反数。2024-01-02 至 01-05 的 `000001.SZ` 与 `600000.SH`，
   本机重算后四舍五入到 6 位小数，与 `wx2.dbo.stock_cutamp.cutamp` 一致。
   2024-01 的 8 行和 2024-02-01 至 02-08 的 12 行已写入 `feature.value` 的不同月份分区。
   同一身份键再写会被拒绝，已有文件不改；同一月份的新身份键追加为新文件。
   2024-03-11 的两只样本股票已追加为 `ym=202403/part-00001.parquet`，digest `a1cd899e6e42a85b00edda28fbf9533a2be13babc4112bd5cee8feeca12b560c`，
   03-01 至 03-08 的 part 文件未改。这两行与 `wx2` 在 6 位小数上一致，同日再写被拒绝。
   窗口不足 20 日不产行。`knowledge_dt` 是窗口内最晚交易日，
   `pit_grade` 取输入最差，拒绝把可见日提前。行情读取差异仍在：旧读取没有 `as_of`；
   新读取按 `as_of` 截断。
   连 `wx2` 时 pymssql 要用 TDS 7.0 且关闭加密。
5. **这个消费者不需要新的源表。** 旧入口是
   `alpha_factory.factor_loader.FactorLoader` 的 `performance_factor_single`：
   读 `wx2.dbo.stock_cutamp.cutamp`，窗口 1 日取均值，再乘 `direction=-1`。
   `stock_cutamp` 是派生表，不迁入。股票池 `all_a` 来自 `ASHAREDESCRIPTION`
   上市满 365 日且未摘牌、排除北交所和 `A` 开头代码。2024-01-05 该池 4860 只，
   其中 4851 只有 `cutamp`。无复权收盘价并列的 1336 只与本机重算在 6 位小数上全部一致；
   603 只不一致，且全部有并列收盘价。2912 只虽有并列但仍一致。旧仓按 pandas
   `sort_values` 默认 quicksort 排并列，新实现按交易日稳定排序。2024-02-02 的
   `000001.SZ` 在新写入的 2 月分区里再次如此：20 日行情与 `wx2` 相同，quicksort 对上旧值。
   因此不切换旧仓消费入口。
   新资产是 `feature_pf_single_cutamp`，不在 `wind_source_refresh` 里。旧仓日更继续跑。
6. **非北交所行情字段已按全部交易日核对。** 比较开高低收、成交量、成交额、涨跌幅、涨跌停和复权收盘价。1990–2013 与 2025–2026 完全相同。2014–2024 里另有 266 个交易日完全相同，2,410 个交易日都有复权收盘价差异：9,355 行四舍五入到分后相同，4,515 行分以上仍不同。后者主要是 `000078.SZ` 2,098 日、`000545.SZ` 1,768 日、`000620.SZ` 343 日、`000693.SZ` 252 日，合计 4,461 行。这四只的不复权收盘价全部相同，复权收盘价的比例等于复权因子的比例；每只股票的比例是常数，较短的一段是该常数的倒数。另有 4 行因子已经相同，复权收盘价仍有尾差。其中 965 个交易日还有涨停价或跌停价一侧为空，共 254,858 个字段；50 个交易日两边都有涨跌停价但数值不同，共 2,790 个字段。2018-01-02 的空值在 `wx2` 一侧。开高低收、成交量、成交额、涨跌幅和代码集合没有差异。
   2026-11-17 补核 `.BJ`。共同的 8,768 个交易日上，行数差仍等于 `.BJ` 行数差。
   多出来的只有 `wx2` 的 20261116，当天 5,579 行，其中 355 行是 `.BJ`，本机还没有这一天。
   两边都有的 `.BJ` 键 284,398 行。十个字段是开高低收、成交量、成交额、涨跌幅、涨跌停和复权收盘价。
   284,386 行全部相同。不一致的 12 行只属于 `832317.BJ`、`833874.BJ`、`833994.BJ`。
   其中 9 行成交量为 0，开高低收、成交额、涨跌幅和复权收盘价相同，涨跌停在 `wx2` 为空、本机有值。
   20211115 的 3 行不复权收盘价相同，复权收盘价不同：`832317.BJ` 是 82.89 对 100.38，
   `833874.BJ` 是 43.61 对 49.82，`833994.BJ` 是 59.74 对 60.64。
   本机另有这三只在 20200727–20211112 的 758 行，`wx2` 没有。
   `wx2` 独有 291,307 行、596 个代码，交易日从 20080221 到 20261116，没有本机行可对。
   其中 189,718 行早于本机北交所起点 20200727，101,234 行落在本机已有其他北交所代码的交易日，355 行是 20261116。
   这 291,307 行的开高低收、成交量、成交额和复权收盘价都有值，涨跌幅空 239 行，
   涨跌停为空的有 290,952 行。

## 依据文档与旧仓证据

- [迁移路线 P0–P6](roadmap.md) 定义阶段顺序、golden 先于新实现、并行对拍和逐条切换。
  上面的三个资产和先迁一个量价因子，是这次讨论按当前进度选定的实施范围。
- [编排架构](../architecture/cli-and-orchestration.md) 与
  [Dagster 选型 ADR](../adr/2026-09-16-dagster-orchestration.md) 定义共享作业函数、依赖、
  物化元数据、控制面及远端调度边界。
- [日历契约](../contracts/trade-calendar.md)、[Wind 日历采集](wind-asharecalendar-ingest.md)、
  [Wind 日行情契约](../contracts/src-wind-ashareeodprices.md) 和
  [PIT 规则](../domain/pit-rules.md) 定义当前数据形态、采集游标与研究可见性。
- [wx2 逐表处置清单](wx2-table-list.md) 决定候选数据去向，
  [端口与适配器](../architecture/ports-and-adapters.md) 约束读取路径，
  [因子多周期 ADR](../adr/2026-09-19-factor-horizons-and-admission.md) 约束后续标签与准入。
- 旧仓 `pycharm_workspace` 在核对时为 `78765aac`。以
  `data/wind_to_sql_2.py:424` 核对原采集续跑，
  `core/market_data_service.py:406` 采集行情 golden 口径，
  `alpha_factory/run_daily_pipeline.py:79` 核对现役因子日更入口。
