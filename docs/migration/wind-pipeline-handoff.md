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
| Wind 日行情 | `ASHAREEODPRICES` 已有数据和成功批次。两张 Wind 表都使用 `OPDATE + OBJECT_ID` 续跑，页尾游标与该页数据同事务提交。多页失败时，已提交页的行数、DML 和页尾游标留在失败日志里；提交结果未知的页不计入、不自动重试。 | 核验源端追平状态、按交易日的覆盖和修订差异。最新批次的业务日期范围是该页范围，不能用来判定历史完整性。 |
| 编排与研究 | 三个资产已接入：`src_wind_asharecalendar`、`std_trade_calendar`、`src_wind_ashareeodprices`。标准日历依赖日历采集，行情采集使用自己的源游标。假源验收了有界回填、一次续跑和 `_batch` 游标。临时实例的资产图能看到这条依赖，行情采集独立。写库仍走双闸。 | 真实 Wind 回填、控制库运行存储，以及带行数和游标的正式运行界面。其后是行情读取端口、对拍和首个量价因子。 |

## 下一轮实施与验收

1. **把三个 Dagster 资产接到真实 Wind，并把运行状态放进控制库。** 正式日历分区和
   假源验收已经完成：采集调用 `ingest_wind_paged()`，物化调用 `materialize_trade_calendar()`。
   标准日历依赖日历采集，行情采集使用自己的源游标。源同步检查点是页尾游标，
   日历资产是整表快照，交易日分区留给以后按日消费的资产。
   接下来用有页数上限的真实回填和一次续跑回读 `_batch`，在界面核对依赖、行数、摘要、
   `as_of`、PIT 等级及采集页尾游标。Dagster 运行表进控制库，不进研究库。
   写库沿用双闸。失败日志保留已提交页；提交结果未知的页不计入、不自动重试。
2. **先对拍行情，再迁一个量价因子。** 从旧仓 `core/market_data_service.py:406`
   的 `get_daily_prices()` 固化 golden 样例，记录旧仓 commit、输入日期和股票、
   字段与缺失行为。对拍分开记录两类差异：`wind_db` 与 `wx2` 在日期、股票、字段上的覆盖、键和修订；同一输入下旧实现与新实现的行为。
   检索现有 ports/adapters 后补齐带 `as_of` 的最小行情读取能力，验证日期闭区间、
   空结果及未来行不可见。随后从现役 Alpha Factory 选一个依赖少的量价因子，
   对拍相同股票池、因子值和缺失域，验收 `knowledge_dt` 与 `pit_grade` 由血缘推导。
3. **按真实消费者扩表和切换。** 以该消费者的实际依赖和逐表清单决定迁哪些源表，
   结合旧下游证据逐表补 visibility，再进行新旧并跑与差异核对。通过后逐条切换消费
   入口并记录旧任务与新资产的对应。旧仓继续承担现役日更，远端 Windows 调度由
   项目负责人维护。后续回测和发布按 P4/P5 的契约推进。

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
