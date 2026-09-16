---
title: 选择 Dagster 作资产化编排
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - orchestration/
  - db/migrations/ops/
supersedes: null
superseded_by: null
---

# 选择 Dagster 作资产化编排

## 背景

旧仓有一套自研调度：`task_scheduler/jobs.json` 定义任务与 `depends_on`
依赖，配轮询执行器，远端 Windows 侧由 Task Scheduler 触发
`scripts/schedule/*.bat`。

它在"按时把东西跑起来"这件事上是够用的。缺的是另外三条：

1. **血缘不可见**。`jobs.json` 的 `depends_on` 是任务级依赖，无法回答
   "这个因子表依赖哪几张源表"。`data_registry` 的物化关系不可追溯。
2. **分区回填困难**。要补一段历史只能整表重算，没有按日期回填的机制。
3. **物化状态无处记录**。不知道某个分区上次成功物化是什么时候，因此无法
   判断数据是否完整。

新架构的数据层是分支式依赖图，跨层直读允许但必须声明——这个设计只有在
血缘可见时才有意义。

## 决策

采用 Dagster 的**资产化编排**（software-defined assets）。

```
orchestration/
├── definitions.py
├── assets/        数据层表达为 asset，含分区与 deps
├── jobs/
├── schedules/
├── sensors/
└── resources/     composition root：适配器注入
```

运行状态落 PG `ops_*` 控制状态面（dagster-postgres）。

### 资产约定

| 约定 | 内容 |
|---|---|
| 命名 | `<layer>_<dataset>` |
| 分区 | 时间序列资产必须有分区 |
| `deps` | 上游资产必须声明 |
| `reads` | 元数据字段，记录实际读取的数据集全集（含跨层直读） |
| 元数据 | 物化后附带行数、`as_of`、`pit_grade`、digest |
| 资产组 | 按研究线分组 |

## 理由

1. **资产模型直接对上三条痛点**。声明 `deps` 得到血缘图，声明分区得到回填
   能力，物化事件自动进运行存储。不需要自己实现这三样。
2. **血缘是数据粒度的，不是任务粒度的**。这正是 `jobs.json` 的
   `depends_on` 缺的东西。
3. **分区回填是内建能力**。按日期范围重跑某个资产是一条命令。
4. **与"跨层直读必须声明"的设计契合**。`reads` 元数据让声明有地方落。
5. **Python 原生**。asset 就是带装饰器的函数，不需要 DSL 或 YAML 配置。
6. **可以渐进接入**。新资产一个个加，旧调度逐条对应后再关停。

## 被否方案

| 方案 | 否决理由 |
|---|---|
| 继续自研调度 | 要自己实现血缘图、分区回填、物化状态记录，工作量大且是重复发明 |
| Airflow | 任务导向而非资产导向，血缘要额外实现；对单人项目偏重 |
| Prefect | 流程编排。本项目的任务串法本来不复杂，复杂的是数据依赖 |
| dbt | SQL 为中心，本项目的计算主体是 Python（因子、模型、回测） |
| Luigi | 社区活跃度低，无资产模型 |
| cron + 脚本 | 回到旧仓的状态，三条痛点全部保留 |

关于 Airflow 与 Prefect：它们解决的是"任务怎么串、失败怎么重试"。本项目的
任务串法很简单（多数是线性或浅依赖），而"这个数字从哪来的"是真正的问题。
选错抽象会导致血缘仍需另建一套。

## 代价

1. **多一个重依赖**。dagster + dagster-webserver + dagster-postgres。因此
   放在 optional extra `orchestration` 里，只跑计算不需要装。
2. **学习曲线**。asset、partition、resource、IO manager 这套概念需要时间
   适应。
3. **运行存储需要一个 PG schema**。已在 `ops_*` 面规划。
4. **本地起 webserver 有资源开销**。交互式研究时不需要起它。
5. **Dagster 版本升级可能有破坏性变更**。锁版本，升级走独立评估。

## 推论

1. **`orchestration/` 是 composition root**，允许依赖全部层；反之业务层
   不得依赖它。由 import-linter 契约强制。
2. **asset 函数体只做依赖组装与调用**，业务逻辑在 `src/quantagent/` 里，
   与 CLI 子命令共享同一组函数。否则业务逻辑无法脱离 Dagster 测试。
3. **运行状态只进 `ops_*`**，研究查询不得读取。见
   [2026-09-16-pg-two-planes.md](2026-09-16-pg-two-planes.md)。
4. **调度按交易日历触发**，不按自然日。日历来自 `domain/calendar`，不在
   调度配置里硬编码日期。
5. **写库仍受铁律约束**。编排不是绕过写入保护的通道。
6. **旧调度项逐条对应到新 asset 后才关停**，对应关系记在迁移路线里。
