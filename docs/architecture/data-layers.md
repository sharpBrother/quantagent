---
title: 数据分层与存储边界
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/ingest/
  - src/quantagent/lake/
  - src/quantagent/adapters/
  - db/
  - frozen/
  - publish/
---

# 数据分层与存储边界

## 数据层是职责划分，不是强制管线

每层定义两件事：**它负责什么数据**，以及**它允许依赖哪些上游**。研究线按需
取用，不要求逐层穿过。

| 层 | 数据职责 | 允许依赖 | 物理位置 |
|---|---|---|---|
| `src` | 源端原生镜像，零加工 | 外部源 | PG `src_*` schema |
| `std` | 标准化：统一资产标识、单位、字段命名与类型；不做业务口径加工 | `src` | `var/lake/std/` |
| `mart` | 口径已对齐的可分析事实：行情、财务、成分、持仓、宏观序列、基础信息，以及股票池成员与前瞻收益 | `std` | `var/lake/mart/` |
| `feature` | 因子值长表与因子评价指标 | `mart` | `var/lake/feature/` |
| `model` | 模型产物与预测值 | `feature`、`mart` | `var/lake/model/`、`var/artifacts/models/` |
| `signal` | 策略信号、回测结果与因子分组净值 | `model`、`feature`、`mart` | `var/lake/signal/` |
| `portfolio` | 组合权重、风险、归因 | `signal`、`mart`、`portfolio`（自身持仓） | `var/lake/portfolio/` |
| `publish` | 发布契约产物 | 以上任意层，以及 `frozen/` | `publish/` |

### 两条硬约束

1. **不得反向依赖**：`mart` 不能读 `feature`，`feature` 不能读 `signal`。
2. **不得同层成环**：同层资产之间不允许循环依赖。`portfolio` 读自身持仓是
   时间维度上的前向依赖（T 日读 T-1 持仓），不构成环。

### 跨层直读必须声明

跨层直读是允许的，但必须在 Dagster 资产定义里显式声明 `reads:`，让血缘图
可见。理由：强制逐层穿过会制造纯转发的中间资产，那是冗余；但如果直读不
声明，血缘就断了，"这个数字从哪来的" 变成不可回答的问题。两害相权，选择
"允许直读 + 强制声明"。

### 四类合法分支

这些都不需要绕路制造中间层：

| 研究线 | 路径 | 跳过了什么 |
|---|---|---|
| 宏观指标展示 | `std` 或 `mart` → `publish` | 因子、模型、信号、组合 |
| 因子评价看板 | `feature` → `publish` | 模型、信号、组合 |
| 规则策略 | `mart` 或 `feature` → `signal` | 模型 |
| 组合风险 | `mart` + 自身持仓 → `portfolio` | 因子、模型、信号 |

`model` 层的存在正是为了让「规则策略跳过模型」这件事在数据面可表达。如果
模型只存在于代码里而数据面没有对应层，就无法区分「这个信号是模型产出的」
和「这个信号是规则产出的」。

## PostgreSQL：两个互不混用的逻辑面

这是「PG 只存原始数据」的准确表述——约束的是研究数据面，控制状态另有归属，
不靠混进源表解决。旧仓 `wx2` 一个库里混着源镜像、派生因子、策略结果、调度
日志，是必须避免的反面案例。

### 研究数据面 `src_*`

schema 按源划分：`src_wind`、`src_tushare`、`src_jydb`、`src_suntime`、
`src_macro`。第一批 59 张源镜像的清单见
[`../contracts/src-plane.md`](../contracts/src-plane.md) 与
`db/src_tables.yaml`。

- **只有 `quantagent.ingest` 可以写。** 其他任何层对它只读。
- **只存源原生结构。** 字段名、类型、语义与源端严格一致，不改含义，不加
  业务字段。
- **派生数据一律不进 PG。** 因子、信号、组合、回测结果全部落 Parquet。

### 控制状态面 `ops_*`

调度水位、批次登记、运行日志、告警状态，以及 Dagster 自带的运行存储。

- **不是研究数据。** 不对 lake 供数，**任何研究查询都不得读取它**。
- **重新建模，不照搬旧结构。** 旧仓的 `task_moniter`（拼写错误、无主键、
  `to_sql(append)` 无约束）、`task_error_detail`、`scheduler_job_run_log`
  在这一层重新设计。
- 迁移序列与研究数据面分开（`db/migrations/ops/` 与 `db/migrations/src/`），
  因为两者的变更频率与风险等级完全不同。

### 源镜像层不做版本留存

PG 只反映源端当前状态，不做 CDC、不保留历史版本。

这是**有意的取舍**：好处是结构简单、存储可控；代价是源端静默修订不可回溯。
因此有一条推论——**源层的时间字段不得被当作 PIT 依据**。尤其是
`_ingested_at`：一次性迁入的存量数据，其 `_ingested_at` 全部等于迁移日，
用它做 PIT 等于伪造历史。

取舍记录见 [../adr/2026-09-16-no-source-vintage-in-pg.md](../adr/2026-09-16-no-source-vintage-in-pg.md)。

补偿手段是**从现在开始积累**：每个采集批次的原始拉取结果 append-only 归档
到 `var/lake/_vintage/<source>/<dataset>/batch_dt=.../`，即使源端不提供发布
时间，也能逐步积累系统时间轴上的版本序列。这件事越早开始收益越大。

### 原生结构与技术元数据如何兼容

源表保持原生，系统侧信息走统一前缀的技术元数据列，不与源字段冲突：

| 列 | 含义 |
|---|---|
| `_batch_id` | 采集批次标识，外键指向 `src_<source>._batch` |
| `_ingested_at` | 本系统采集时间。**不是 PIT 依据** |
| `_row_hash` | 行内容哈希，用于幂等与变更检测 |

旁表 `src_<source>._batch` 登记批次：拉取窗口、源端游标位点、行数、digest、
成功或失败原因。

未来若某个数据集确需版本语义，走「新增旁表 + 契约声明」的扩展路径，**不改
原生表**。

## Parquet Lakehouse

`var/lake/` 下按层分目录，是所有派生事实的唯一事实源。

```
var/lake/
├── std/         标准化
├── mart/        分析事实表
│   ├── universe_member/  股票池成员区间表
│   └── forward_return/   前瞻收益（usage: evaluation_only）
├── feature/
│   ├── value/       因子值长表
│   ├── metric/      因子评价指标长表
│   └── _registry/   因子定义与参数注册表
├── model/       模型产物与预测
├── signal/      信号与回测结果
│   └── group_nav/   因子分组净值
├── portfolio/   组合、风险、归因
├── _matrix/     训练宽矩阵缓存（纯派生，可整体删除重建）
├── _vintage/    批次原始快照归档（append-only）
└── legacy/      从 wx2 冻结迁入的不可重算历史制品（只读）
```

每个派生数据集的键、层归属与 `knowledge_dt` 推导见
[derived-datasets.md](derived-datasets.md)。

分区键、目标文件大小、排序键与压缩参数以 P1 的 benchmark 结论 ADR 为准，
见 [feature-storage.md](feature-storage.md)。在结论出来之前不固化约定。

## DuckDB

纯查询引擎。**不持久化 `.duckdb` 文件**，每次会话从 Parquet 挂载。

理由：`.duckdb` 一旦持久化就变成第二个事实源，需要自己的备份、迁移和版本
管理，而它提供的能力（索引、事务）在单机只读分析场景里收益有限。保持
Parquet 为唯一事实源，DuckDB 随时可替换。

会话管理在 `platform/duck/`，读取封装在 `adapters/lake/`。

## 入 git 的只有两个数据目录

| 目录 | 方向 | 内容 |
|---|---|---|
| `frozen/` | 输入 | 冻结输入制品，不可重算，发布前提。见 [../../frozen/README.md](../../frozen/README.md) |
| `publish/` | 产出 | 小体积发布 JSON，展示层唯一来源。见 [../../publish/README.md](../../publish/README.md) |

`var/` 整体 gitignore。这一条把 `.gitignore` 从旧仓的 320 行（其中 110 条
是 `reports/` 的逐任务例外）压到十几行。

旧仓的体积问题值得记住：工作树 4.5G、`.git` 573M、`data_registry/` 389M
全量入库、115 个超过 1MB 的文件被跟踪。根因是「产物该不该入库」没有一条
简单规则，只能逐个开例外。现在的规则是：**能重算的不入库，不能重算且发布
必需的入 `frozen/`，发布产物入 `publish/`，其余一律 `var/`**。

## 写入保护

任何写入 PG 或写入 `frozen/` / `publish/` 的操作都受 `AGENTS.md` 的数据
安全铁律约束：默认不写、目标白名单、insert-only、不覆盖既有行、写后回读、
事务状态未知不重试。这些是写入函数的内建行为，不依赖任何授权流程。
