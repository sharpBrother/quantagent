---
title: CLI 与编排
status: active
created: 2026-09-16
updated: 2026-09-18
applies_to:
  - src/quantagent/cli/
  - orchestration/
  - notebooks/
---

# CLI 与编排

## 问题：可执行代码没有归属

旧仓的数字：`scripts/` 316 个脚本，只有约 8%（25 个左右）是长期入口——
出现在 `task_scheduler/jobs.json` 或现役文档里；约 81% 既不在调度也不在
现役文档中。此外还有 `scripts/schedule/` 下的 `.bat` 与 Windows Task
Scheduler 的远端配置，实际触发链条跨了两处。

这不是纪律问题。根因是「一段可执行代码该往哪放」没有答案，于是全都放进
`scripts/`，然后无法区分哪些还在用。

## 解法：入口只有两处，加一个草稿区

| 归属 | 用途 | 判断标准 |
|---|---|---|
| `quantagent <group> <command>` | 人手动触发的操作 | 需要参数、需要交互、按需运行 |
| Dagster asset / job | 有数据产出、有依赖关系、需要调度 | 产出落 lake 或 publish |
| `notebooks/` | 探索性分析 | 一次性、结论待定、不被依赖 |

**没有 `scripts/` 目录。** pre-commit 钩子 `no-scripts-dir` 与 CI 的
`禁止 scripts/ 目录` 都会拦它出现。

这条规则的有效性依赖前两处足够好用。如果 CLI 难用，人还是会想建
`scripts/`——所以 CLI 的设计目标是"比写一个脚本更省事"。

## 统一 CLI

### 分组按动作对象

使用者找命令时想的是"我要刷新因子"而不是"我要调用 features 模块"，所以
分组按动作对象划分：

```
quantagent ingest tushare trade-cal [--start --end --exchange --write-db]
quantagent lake benchmark-layout [--scale tiny|paper --rebuild]
quantagent lake materialize trade-calendar [--as-of --rebuild]
quantagent calendar is-open --exchange --cal-dt --as-of
quantagent calendar shift --exchange --origin --n --as-of
quantagent feature window --feature-id --definition-version --param-hash --start --end --as-of
quantagent feature cross-section --event-dt --as-of
quantagent feature matrix --start --end --feature-keys --asset-ids --as-of
quantagent feature metric --feature-id --definition-version --param-hash --universe-id --horizon --metric-id --window --benchmark-id --start --end --as-of
quantagent forward-return window --horizon --return-kind --benchmark-id --start --end --as-of
quantagent group-nav window --feature-id --definition-version --param-hash --universe-id --horizon --run-id --start --end --as-of
quantagent universe members --universe-id --dt --as-of
quantagent model <action>         train / predict / evaluate
quantagent backtest <action>      run / compare / report
quantagent portfolio <action>     construct / risk / attribute
quantagent publish <action>       build / validate / diff
quantagent db <action>            migrate / status / ddl-dump
quantagent check <action>         contracts / docs / frozen / lineage
```

矩阵的 `--feature-keys` 接收 JSON 数组，必须逐因子提供完整身份，例如：

```sh
quantagent feature matrix --start 2024-01-01 --end 2024-01-31 --as-of 2024-02-01 \
  --asset-ids A0000 \
  --feature-keys '[{"feature_id":"mom_20d","definition_version":"v1","param_hash":"p0"}]'
```

原 `--feature-ids` 已移除，不自动选择最新版本或默认参数。

`quantagent --help` 是「这个系统有哪些能力」的权威答案。Typer 自动生成，
不需要单独维护命令索引——旧仓需要维护脚本清单文档，那份文档必然过期。

### 子命令只做三件事

解析参数、组装依赖、调用业务函数。子命令函数体膨胀到几百行是明确的信号：
业务逻辑写在了入口层，既无法测试也无法被 Dagster 复用。

### CLI 与 Dagster 共享业务函数

两者都是 composition root，调用同一组业务函数，不各写一遍。旧仓的
`scripts/*.py` 与调度的 `.bat` 之间存在这种重复，导致手动跑和调度跑的行为
可能不同。

### 写入相关的子命令

- `--write-db` 默认关闭
- 同时要求 `QUANTAGENT_ALLOW_DB_WRITE=true`
- 干跑模式打印将要执行的 DML 条数与目标表，不执行
- 写入前后各回读一次，落 run log

双重开关是刻意的冗余：环境变量防止误在生产档位运行，命令行参数防止误在
正确档位下手抖。

## Dagster 资产化编排

### 为什么是资产化

本项目的真实痛点是三条：

1. **血缘不可见**：「这个数字从哪来的」不可回答。旧仓 `data_registry` 的
   物化关系不可追溯。
2. **分区回填困难**：要补一段历史只能整表重算。
3. **物化状态无处记录**：不知道某个分区上次成功物化是什么时候。

资产模型直接对上这三条：声明 `deps` 得到血缘图，声明分区得到回填能力，
物化事件自动进运行存储。

流程编排（Prefect 那类）解决的是"任务怎么串"，而本项目的任务串法本来就
不复杂。旧仓的自研调度器（`jobs.json` + 轮询 + 远端 Task Scheduler）在
"按时跑起来"这件事上是够用的，它缺的恰好是上面三条。

选型记录见 [../adr/2026-09-16-dagster-orchestration.md](../adr/2026-09-16-dagster-orchestration.md)。

### 资产约定

| 约定 | 内容 |
|---|---|
| 命名 | `<layer>_<dataset>`，如 `mart_equity_eod`、`feature_momentum` |
| 分区 | 时间序列资产必须有分区，按交易日或月。无分区就无法按日回填 |
| `deps` | 上游资产必须声明。跨层直读同样声明，让血缘完整 |
| `reads` | 元数据字段，记录实际读取的数据集全集（含跨层直读），供血缘图与契约校验消费 |
| 元数据 | 物化后附带行数、`as_of`、`pit_grade`、digest |
| 资产组 | 按研究线分组（`group_name`），便于按线重跑 |

`reads` 与 `deps` 的区别：`deps` 是 Dagster 的执行依赖（决定调度顺序），
`reads` 是数据依赖的完整声明（决定血缘图）。通常两者一致；不一致的情形是
读取了不由本系统物化的外部输入（如 `frozen/` 的冻结制品）。

### 运行状态

落 PG `ops_*` 控制状态面，与研究数据面分开演进（`db/migrations/ops/`）。
研究查询不得读取 `ops_*`。

### 调度

按交易日历触发，不按自然日。非交易日不跑，半日市按实际收盘时间。日历来自
`domain/calendar`，不在调度配置里硬编码日期。

### 远端部署

若部署到远端 Windows，Task Scheduler 的触发器、账户、工作目录由项目负责人
手工维护。代码侧只提供命令与核验方式，不自动改远端配置。

## notebooks 的治理

`notebooks/` 是探索性代码的唯一去处，规则见
[../../notebooks/README.md](../../notebooks/README.md)。要点：

- jupytext 配对，只提交 `.py`，`.ipynb` 已 gitignore
- 命名带日期与主题，日期是过期判定的依据
- 超过 6 个月未修改且结论未被任何文档引用的直接删除
- 有价值的结论在删除前提炼进 `docs/research/`
- `src/` 与 `orchestration/` 不得 import notebook
- notebook 里不允许写库

notebook 是草稿，不是知识载体。这个定位明确了，就不会积累出一堆"不敢删但
也没人看"的文件。

## 迁移期的过渡

P2–P5 期间旧仓仍在运行，两套系统并存。过渡规则：

1. 新系统的入口一律按本文档的规则建，不因"临时"而破例。
2. 旧脚本不迁移，重写为 CLI 子命令或 asset。迁移判定见
   [legacy-inventory.md](legacy-inventory.md)。
3. 旧调度项逐条对应到新 asset 后才关停，对应关系记在
   [../migration/roadmap.md](../migration/roadmap.md)。
