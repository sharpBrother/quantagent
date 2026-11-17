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

## 当前状态 · 2026-11-15

| 项目 | 已验证 | 待完成 |
|---|---|---|
| PostgreSQL | 本地研究库和控制库可连通，迁移分别为 8 和 2，待应用均为 0。五个源 schema 的现有表和序列已授权，`leo` 新建对象会自动授权给 `quantagent_ingest`。项目环境已安装 Dagster 和 pymssql。本机未配置 Wind 源库。只读 `wx2` 在端口映射重启后可以登录。`ops` 已有 21 张 Dagster 运行表，`public` 里没有。 | 确认 Dagster 执行端能同时访问 Wind、目标 PG 与物化目录。 |
| Wind 日历 | `ASHARECALENDAR` 已初始化，31,483 条开市记录、5 个市场代码。提交 `f9abaf3` 已将 `scan_trade_cal()` 和标准日历上游切到 Wind。`quantagent lake materialize trade-calendar --as-of 2026-11-15` 写入正式分区 47,389 行，digest `b6d8463d8b7e29b0a9bcc08cc54f8a11e37ac85da68b397a33259968e64d0e9c`。SSE 上 2026-11-13 开市、14 与 15 日闭市，上一交易日是 13 日；`as_of=2026-11-15` 读不到 11-16。 | 正式分区已可读。后续由 `std_trade_calendar` 资产重跑，不覆盖既有文件，除非显式 rebuild。 |
| Wind 日行情 | `ASHAREEODPRICES` 18,870,269 行，8,768 个交易日，1990-12-19 至 2026-11-13。与 `wx2` 的交易日集合相同。`wx2` 多 290,194 行，每个交易日的行数差都等于 `.BJ` 行数差。`wx2` 的北交所行情从 2008-02-21 起共 575,350 行，本机从 2020-07-27 起共 285,156 行。行数不同的 3,918 个交易日止于 2024-04-03，之后每天行数相同。2026-11-13 两边都是 5,579 行，开高低收、成交量、成交额、涨跌幅、涨跌停和复权收盘价逐行相同。非北交所代码的 10 个行情字段已按全部 8,768 个交易日核对。1990–2013 与 2025–2026 共 6,358 个交易日完全相同。2014–2024 有 2,410 个交易日至少有一行不同，代码集合没有差别。开高低收、成交量、成交额和涨跌幅也没有不同。 | 下一次真写要等游标 `2026-11-13T15:09:05` 之后出现新行。`wx2` 独有的早期北交所行没有逐字段比较。 |
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
5. **指数日行情已落地。** 2026-11-17 核对 `src_wind.AINDEXEODPRICES`：全表 24598322 行；
   `000985.CSI` 5311 行，`TRADE_DT` 从 20041231 到 20261116；最新成功游标 `opdate` 为
   2026-11-16T21:26:24。采集命令仍是 `quantagent ingest wind AINDEXEODPRICES`，游标与
   A 股日行情相同。可见性是 `TRADE_DT` 的 `same_day_close` / A。
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
   这 4861 行没有写入长表。旧表 `stock_tr_umr` 不迁，旧入口不切。
6. **达到 3GB 的源表按体积从大到小采集。** 命令是 `quantagent ingest wind large`。
   顺序：`ASHAREMONEYFLOW` 32GB、`ASHAREEODDERIVATIVEINDICATOR` 19GB、
   `ASHAREEODPRICES` 15GB、`ASHARECASHFLOW` 6.4GB、`ASHAREINCOME` 5.8GB、
   `ASHAREBALANCESHEET` 3.7GB、`AINDEXVALUATION` 3GB。
   默认每张干跑 1 页。真写要开写闸，并且不要传 `--max-pages`。
   开跑前用 `wind_db` 的列清单对采集列，不一致就停。
   `ASHAREMONEYFLOW` 是空表，已去掉源端没有的 `GSUPDTIME`。
   `ASHAREEODPRICES` 已有数据，`GSUPDTIME` 仍留在物理表里、不采集。
   截图里的 `Bond_CBYieldCurveAll` 不在第一批源表，这次不接。本机不跑这批数据。
2. **首个量价因子已对上一个小样本。** `pf_single_cutamp_1_mean_neg` 来自旧仓
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
3. **这个消费者不需要新的源表。** 旧入口是
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
4. **非北交所行情字段已按全部交易日核对。** 比较开高低收、成交量、成交额、涨跌幅、涨跌停和复权收盘价。1990–2013 与 2025–2026 完全相同。2014–2024 里另有 266 个交易日完全相同，2,410 个交易日都有复权收盘价差异：9,355 行四舍五入到分后相同，4,515 行分以上仍不同。后者主要是 `000078.SZ` 2,098 日、`000545.SZ` 1,768 日、`000620.SZ` 343 日、`000693.SZ` 252 日，合计 4,461 行。这四只的不复权收盘价全部相同，复权收盘价的比例等于复权因子的比例；每只股票的比例是常数，较短的一段是该常数的倒数。另有 4 行因子已经相同，复权收盘价仍有尾差。其中 965 个交易日还有涨停价或跌停价一侧为空，共 254,858 个字段；50 个交易日两边都有涨跌停价但数值不同，共 2,790 个字段。2018-01-02 的空值在 `wx2` 一侧。开高低收、成交量、成交额、涨跌幅和代码集合没有差异。`wx2` 独有的早期 `.BJ` 行没有逐字段比较。

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
