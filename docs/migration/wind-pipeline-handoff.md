---
title: Wind 数据链路迁移交接
status: active
created: 2026-11-15
updated: 2026-11-15
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
| PostgreSQL | 本地研究库和控制库可连通，迁移分别为 8 和 1，待应用均为 0。五个源 schema 的现有表和序列已授权，`leo` 新建对象会自动授权给 `quantagent_ingest`。项目环境已安装 Dagster。 | 确认 Dagster 执行端能同时访问 Wind、目标 PG 与物化目录。本机当前未配置 Wind，未安装 pymssql。控制库还没有 Dagster 运行表。 |
| Wind 日历 | `ASHARECALENDAR` 已初始化，31,483 条开市记录、5 个市场代码。提交 `f9abaf3` 已将 `scan_trade_cal()` 和标准日历上游切到 Wind。`quantagent lake materialize trade-calendar --as-of 2026-11-15` 写入正式分区 47,389 行，digest `b6d8463d8b7e29b0a9bcc08cc54f8a11e37ac85da68b397a33259968e64d0e9c`。SSE 上 2026-11-13 开市、14 与 15 日闭市，上一交易日是 13 日；`as_of=2026-11-15` 读不到 11-16。 | 正式分区已可读。后续由 `std_trade_calendar` 资产重跑，不覆盖既有文件，除非显式 rebuild。 |
| Wind 日行情 | `ASHAREEODPRICES` 18,870,269 行。2026-11-15 公司端在 `8590e16` 上干跑，游标 `2026-11-13T15:09:05` / `7700421104` 之后 `pages=0`。起点游标仍能取到 2002-04-29 的行，读取器有效。`_batch` 未变。 | 按交易日核对本机覆盖和修订。游标追上不等于每个交易日都完整。下一次真写要等该游标之后出现新行。 |
| 编排与研究 | 三个资产已接入。日行情按 `as_of` 读取。`pf_single_cutamp_1_mean_neg` 在 2024-01-02 至 01-05 的两只样本股票上，重算值四舍五入到 6 位后与 `wx2.stock_cutamp` 一致。这 8 行已写入 `feature.value`，`knowledge_dt` 等于截面日。 | 控制库运行存储，以及带行数和游标的正式运行界面。旧仓日更尚未切换。 |

## 下一轮实施与验收

1. **真实源烟测已结束，运行存储仍待接入控制库。** 2026-11-15 在 `8590e16` 上，
   日历与日行情干跑都是 `pages=0`，未真写。取数条件是 `OPDATE` 更大，或同一
   `OPDATE` 下 `OBJECT_ID` 更大；起点游标探针能取到历史行，所以这是游标后无行。
   `_batch` 按 `_batch_id DESC LIMIT 20` 会只看到日历，因为日历批次号更新。
   看某张表要用该 dataset 自己的最大成功批次。下一次真写等到游标之后有新行再做，
   仍必须带 `--max-pages 1`。Dagster 运行表进控制库，不进研究库。
   写库沿用双闸。失败日志保留已提交页；提交结果未知的页不计入、不自动重试。
2. **首个量价因子已对上一个小样本。** `pf_single_cutamp_1_mean_neg` 来自旧仓
   `CUTAMP`：20 个交易日的振幅，去掉收盘触及涨跌停的日子，按复权收盘价切 25%。
   Current-20 取相反数。2024-01-02 至 01-05 的 `000001.SZ` 与 `600000.SH`，
   本机重算后四舍五入到 6 位小数，与 `wx2.dbo.stock_cutamp.cutamp` 一致。
   这 8 行已写入 `feature.value`，窗口不足 20 日不产行。`knowledge_dt` 是窗口内最晚交易日，
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
   `sort_values` 默认 quicksort 排并列，新实现按交易日稳定排序。因此不切换旧仓消费入口。
   新资产是 `feature_pf_single_cutamp`，不在 `wind_source_refresh` 里。旧仓日更继续跑。

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
