---
title: wx2 逐表处置标准
status: active
created: 2026-09-16
updated: 2026-09-18
applies_to:
  - db/migrations/
  - db/src_tables.yaml
  - docs/migration/wx2-table-list.md
  - docs/migration/wx2-table-list.yaml
  - src/quantagent/ingest/
  - src/quantagent/contracts/visibility/
---

# wx2 逐表处置标准

## 不存在「wx2 全量迁 PG」这个动作

旧 SQL Server 库 `wx2` 一个库里混着四类职责：源镜像、派生因子、策略结果、
调度日志。整库搬到 PostgreSQL 会把这个混层直接复刻过去，等于没有重构。

取而代之的是一张**逐表定性的处置清单**。每张表必须落到下面五类之一，
**无归属的表不允许进入新系统**。

## 五类处置

| 数据类别 | 判定依据 | 去向 | 附加约束 |
|---|---|---|---|
| 仍在使用的源数据及可得的修订历史 | 有现役消费者，且是外部源的镜像 | PG 研究数据面 `src_*` | 保持源端原生结构；修订历史仅在源端原生携带时迁入，**不得补造** |
| 可以重算的派生数据 | 因子值、打分、暴露、评分表等，输入与算法都在新链路内 | **不迁移**，在新计算链路重建 | 迁移完成后与旧库做交叉校验，差异需有解释 |
| 无法重算但仍有价值的历史结果 | 依赖已失效的外部输入或已丢失的中间状态 | 冻结为历史制品，落 `var/lake/legacy/` | 独立命名空间，只读；契约强制 `recomputable: false`、`pit_grade: D`、`origin: wx2`；**禁止与重算数据静默混用** |
| 调度、水位、运行状态 | `scheduler_job_run_log`、`task_moniter`、`task_error_detail` 等 | PG 控制状态面 `ops_*` | **重新建模，不照搬旧结构** |
| 已无消费者的数据 | 反查代码与调度均无引用 | **不迁移**，留在旧仓追溯 | 清单中记录表名与判定依据，保留旧仓 commit 指针 |

## 各类别的补充说明

### 第一类：源数据

「修订历史仅在源端原生携带时迁入，不得补造」这条不可让步。源端只给当前值
的数据集，迁入后就只有当前值；不允许用采集批次、迁移时间或任何推测方式
构造版本序列。

迁入的同时必须定版可见性规则。由于存量数据的修订史已丢失，多数会是：

```yaml
visibility:
  rule: source_field          # 若源端原生有公告日
  field: ann_dt
  grade: A
pit_recoverable: false        # 修订史已丢失
pit_from: <迁移日>
origin: wx2
```

注意 `grade: A` 与 `pit_recoverable: false` 可以并存——公告日字段本身是
可信的（A 级），但历史修订版本已不可恢复（`pit_from` 之前的"当时可见的
版本"无法还原）。这两件事是独立的。

### 第二类：可重算的派生数据

不迁移是原则，交叉校验是验收手段。校验方式：

1. 新链路重算某个历史区间
2. 与旧库同区间的值逐值比对
3. 差异逐项归因：新实现 bug、旧实现 bug、或口径变更
4. 口径变更的情形在 `docs/adr/` 记录

因子值属于这一类，见
[../adr/2026-09-16-feature-long-table.md](../adr/2026-09-16-feature-long-table.md)。

### 第三类：不可重算的历史结果

关键约束是**禁止与重算数据静默混用**。

实现方式：落 `var/lake/legacy/` 独立命名空间，契约里三个标记必须齐全
（`recomputable: false`、`pit_grade: D`、`origin: wx2`）。任何同时读取
legacy 与重算数据的查询，结果的 `pit_report` 里 `worst_grade` 自动变成 D，
并在发布层强制展示。

这样"用了不可重算的旧数据"不会被隐藏，但也不被阻断——符合声明式管控的
设计，见 [../domain/pit-rules.md](../domain/pit-rules.md)。

**注意与 `frozen/` 的区别**：`var/lake/legacy/` 是不可重算的**研究数据**，
体积可能很大，不入 git；`frozen/` 是不可重算的**发布输入**，体积小，入
git。判断标准：发布链路是否直接读它。

### 第四类：控制状态

重新建模而不照搬，有具体理由：

| 旧表问题 | 新建模要求 |
|---|---|
| `task_moniter` 表名拼写错误 | 改正为 `task_monitor` 或按新语义重命名 |
| `task_moniter` 无主键，`to_sql(append)` 无约束写入 | 必须有主键与非空约束 |
| 运行日志与源表平级共存 | 归 `ops_*` schema |
| 告警接收人与内网 IP 硬编码在代码里 | 进配置 |

Dagster 的运行存储会承担一部分职责（物化事件、运行记录），因此不是所有旧
调度表都需要对应的新表——先确认 Dagster 覆盖了哪些，剩下的才建表。

### 第五类：无消费者

不迁移，但**必须记录判定依据与旧仓 commit 指针**。理由：三个月后有人问
"那张表呢"，需要能回答"在旧仓某个 commit，判定为零消费者，依据是 X"。

## 清单的生成方式：代码反查，不是人工回忆

输入三份：

1. **`task_scheduler/jobs.json`**：调度中的任务清单，反查每个任务读写哪些表
2. **现役模块的 SQL 引用**：grep 现役模块（排除 `legacy/`、`sandbox/` 等
   已判丢弃的目录）中的表名，得到代码级消费关系
3. **`data_registry` 消费关系**：已登记的物化与消费关系

方法：

```
对每张 wx2 的表：
  消费者 = (调度任务中引用的) ∪ (现役代码中引用的) ∪ (data_registry 中登记的)
  若 消费者 为空 → 第五类
  否则按「是否源镜像」「是否可重算」「是否控制状态」判定前四类
```

反查要注意的陷阱：

- 表名可能出现在字符串拼接的 SQL 里，grep 要覆盖片段匹配
- 表名可能出现在配置或 JSON 里，不只在 `.py` 里
- 同名表在不同 schema 下可能是不同的东西
- 有些消费者是 notebook 或一次性脚本，要判断是否算"现役"

零消费者的表直接归入第五类，不需要进一步判断它是什么性质——既然没人用，
它是源数据还是派生数据都不影响处置。

## 清单是 P2 的第一个交付物

**未完成前不启动任何迁移动作。**

理由：如果先迁一部分再定清单，会出现"已经迁进来但发现应该不迁"的情况，
而删除已迁入的数据比一开始不迁麻烦得多——它可能已经有了下游依赖。

逐表清单在 [wx2-table-list.md](wx2-table-list.md)（机器可读副本
[wx2-table-list.yaml](wx2-table-list.yaml)）：表名、行数、判定类别、判定依据、
去向、附加约束。**该清单是评审基线**（2026-09-18 已按采集代码勘误分类与拟去向）。
旧仓指针 `pycharm_workspace@7c506d511`。行数未连 wx2，一律未查。
**仍不启动迁入，不定版 visibility YAML。** `src_tables.yaml` / DDL 尚未按清单拟去向改名。

## 迁移期的只读适配器

P2 期间需要一个只读的 SQL Server 适配器用于读取 `wx2` 存量。约束：

- **只读**。不提供任何写入能力
- **仅在 P2 期间存在**，迁移完成后连同 `QUANTAGENT_LEGACY_MSSQL_*` 配置
  一并删除
- 不实现 `domain.ports` 的 Protocol——它不是长期读取路径，只是迁移工具

不让它实现 Protocol 是刻意的：如果它实现了，业务代码就可能开始依赖它，
"临时"就会变成永久。

## 与其他两份清单的分工

- 代码模块：[../architecture/legacy-inventory.md](../architecture/legacy-inventory.md)
- 数据表：[wx2-table-list.md](wx2-table-list.md)
- 文档与制品：[docs-and-artifacts-disposition.md](docs-and-artifacts-disposition.md)

三份清单的分类标准不同，不要互相套用：代码看"逻辑是否还要用"，数据表看
"能否重算"，文档制品看"内容是否还在起作用"。
