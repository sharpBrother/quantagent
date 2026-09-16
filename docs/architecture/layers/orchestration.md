---
title: orchestration 层职责
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - orchestration/
  - db/migrations/ops/
---

# orchestration：Dagster 资产化编排

## 负责

| 子模块 | 职责 |
|---|---|
| `assets/` | 把数据层表达为 Dagster asset，含分区定义与 `deps` |
| `jobs/` | 资产子集的成组执行 |
| `schedules/` | 时间触发，按交易日历 |
| `sensors/` | 事件触发，如上游文件就绪 |
| `resources/` | composition root：适配器注入、连接配置 |
| `definitions.py` | 汇总入口 |

运行状态落 PG `ops_*` 控制状态面。

## 不负责

任何业务逻辑。asset 函数体只做依赖组装与调用，与 CLI 子命令共享同一组业务
函数。

## 允许依赖

全部层（composition root 的特权）。反之业务层不得 import `orchestration`。

## 为什么选资产化编排

本项目的真实痛点是三条：血缘不可见、分区回填困难、物化状态无处记录。资产
模型直接对上这三条——asset 声明 `deps` 就得到血缘图，声明分区就得到回填
能力，物化事件自动进运行存储。

流程编排（Prefect 那类）解决的是"任务怎么串"，而本项目的任务串法本来就不
复杂，复杂的是"这个数字从哪来的"。

旧仓的自研调度器（`task_scheduler/jobs.json` + 轮询 + 远端 Windows Task
Scheduler）在"按时跑起来"这件事上是够用的，它缺的恰好是上面三条。

## 硬约束

- **资产必须声明 `reads:`**。跨层直读是允许的，但必须在资产定义里显式声明，
  让血缘图完整。这是"分层不是强制管线"能成立的前提。
- **资产必须有分区**。时间序列资产按交易日或月分区，回填与重跑都依赖它。
- **运行状态只进 `ops_*`**，不与研究数据混。研究查询不得读取 `ops_*`。
- **写库仍受铁律约束**。编排不是绕过写入保护的通道，asset 里的写入同样
  默认关闭、走白名单、insert-only、写后回读。
- **远端配置由人维护**。若部署到远端 Windows，Task Scheduler 的触发器、
  账户、工作目录由项目负责人手工维护，代码侧只提供命令与核验方式。

## 典型反例

- **在 asset 里写业务逻辑**。asset 膨胀会让业务逻辑无法脱离 Dagster 测试。
- **不声明分区的时间序列资产**。缺分区就无法按日回填，只能整表重算。
- **把 Dagster 运行存储和研究数据放同一 schema**。两者的变更频率、风险
  等级和回滚策略完全不同，混在一起会让"改调度"和"改源镜像"互相阻塞。
  迁移序列也因此分开（`db/migrations/ops/` 与 `db/migrations/src/`）。
- **告警硬编码接收人与内网地址**。旧仓写死了
  `172.18.62.252:8000` 和接收人工号。这类参数进配置。
- **依赖关系靠执行顺序隐式表达**。旧仓 `jobs.json` 用 `depends_on` 表达
  依赖，但那是任务级依赖，不是数据级依赖——它无法回答"这个因子表依赖哪几
  张源表"。资产依赖必须落在数据粒度上。

## 对应的机械检查

- import-linter `分层方向单向`：`orchestration` 在最上层。
- import-linter `业务层不得依赖 composition root`。
