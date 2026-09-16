---
title: 因子存储：逻辑格式与物理设计
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/features/
  - src/quantagent/models/matrix/
  - src/quantagent/lake/partitions/
---

# 因子存储：逻辑格式与物理设计

## 现状订正

旧项目不是清一色「一因子一表」，而是**两套模式并存**：

- `factors/` 沿用 `stock_<factor>` 模式，运行时 `if not exists ... CREATE
  TABLE` 建表。问题是表数量爆炸、跨因子 JOIN 昂贵、需事后补覆盖索引
  （`docs/create_performance_factor_single_indexes.sql` 就是补救产物）。
- `alpha_factory_factor_value_d` 已经是带 `visible_date` 的长表。

所以新设计不是从零发明长表，而是**把 alpha_factory 已验证的长表模式确立为
唯一标准**，并补齐它缺的版本与参数语义。

## 长表是唯一的交换与保存格式

`var/lake/feature/` 下的长表是因子的事实源。所有跨模块交换、持久化、发布
都以它为准。

### 字段

| 字段 | 类型 | 含义 | 填法 |
|---|---|---|---|
| `event_dt` | date | 因子截面日 | 计算输入 |
| `asset_id` | string | 资产身份 | 计算输入 |
| `feature_id` | string | 因子语义身份，如 `mom_20d` | 计算输入 |
| `definition_version` | string | 计算逻辑版本 | 因子声明 |
| `param_hash` | string | 参数配置指纹 | 从参数集计算 |
| `value` | float64 | 因子值 | 计算输出 |
| `knowledge_dt` | date | 因子可见日 | **自动派生**，见下 |
| `pit_grade` | enum(A/B/C/D) | PIT 可信等级 | **自动继承**，见下 |
| `computed_at` | timestamp | 计算时刻 | 运行时写入 |
| `run_id` | string | 运行身份 | 运行时写入 |

因子**不带** `published_at` 与 `ingested_at`——那是源层概念，因子没有
「发布」这件事。

### 身份三段拆分

`feature_key = (feature_id, definition_version, param_hash)`。

| 段 | 语义 | 变更触发 |
|---|---|---|
| `feature_id` | 「这是什么因子」 | 语义变了才换 |
| `definition_version` | 「怎么算的」 | 算法实现改变 |
| `param_hash` | 「用什么参数算的」 | 窗口、去极值阈值、中性化方案等参数改变 |

**定义与参数分别记录**是刻意的。合成一个 `feature_version` 会让「换了
参数」和「改了算法」无法区分，也无法分别回滚——而这两件事的性质完全不同：
换参数是研究动作，改算法可能是修 bug。

长表只存两个短字段；配置全文与算法元信息存旁置注册表，避免把长 JSON 塞进
每一行。

### 注册表

```
var/lake/feature/_registry/
├── definitions/<feature_id>/<definition_version>.json
│     算法描述、输入依赖、计算延迟、可见性规则引用、代码位置与 commit
└── params/<param_hash>.json
      参数集全文、生成该 hash 的规范化方式
```

`param_hash` 由参数集的规范化 JSON 计算（键排序、数值规范化），保证同一组
参数在任何机器上得到同一个 hash。

## knowledge_dt 与 pit_grade 自动推导

这两个字段**不接受人工填写**。写入函数拒绝调用方传入的值。

- `knowledge_dt` 默认 = 所有输入 `knowledge_dt` 的最大值 + 因子自身声明的
  计算延迟。因子可以声明**更严格**的规则（更晚可见），不允许更宽松。
- `pit_grade` 沿依赖图取最差值继承（木桶原理），不可手工抬升。

理由：防止「用低可信数据算出的因子被当作高可信使用」。如果这两个字段可以
手填，那么一个 D 级输入产出的因子被标成 A 级，只需要一次疏忽。

具体规则与等级定义见 [../domain/pit-rules.md](../domain/pit-rules.md)。

## 训练用宽矩阵是可重建的派生物化

不要求每次训练都全量 pivot。`models/matrix/` 按需物化宽矩阵到
`var/lake/_matrix/`，由一个组合键唯一确定：

```
matrix_id = digest(
    feature_set_id,
    universe_id,
    date_range,
    as_of,
    {feature_key: (definition_version, param_hash)} 的全集
)
```

即**宽矩阵与输入版本强绑定**。命中则直接复用，未命中则从长表构建并落盘。

任一输入因子的 `definition_version` 或 `param_hash` 变化都会改变
`matrix_id`，旧缓存自然失效。这堵住了一类静默错误：改了参数，但训练还在
读旧矩阵，结果看起来正常只是用错了数据。

`_matrix/` 是**纯缓存**：可随时整体删除重建，不是事实源，不入 git，不参与
发布。任何从 `_matrix/` 直接取数做分析的行为都是错的——一旦有人这么做，
缓存就不能随意删除了，它事实上变成第二份因子存储。

## 物理布局：候选方案与实测定夺

**日分区只是候选，不写死。** P1 阶段做 benchmark 后出 ADR，在结论出来之前
不固化约定。

### 待比较的维度

#### 分区键

候选：`dt=YYYY-MM-DD`（日）、`ym=YYYYMM`（月）、`year=YYYY`；`asset_class`
与 `freq` 作为前缀分区。

**一条明确的反面约束：`feature_id` 不进分区键。** 全A 约 5500 只乘 200 个
因子，若按 `(dt, feature_id)` 双层分区会碎成每文件几千行的 KB 级小文件，
DuckDB 的元数据扫描会被拖垮。分区数量的增长必须是可控的。

#### 目标文件大小

在 64–512MB 区间实测。粗估 200 因子时日分区单日约 110 万行，量级尚可；但
稀疏因子与低频因子（月频宏观、季频财务派生）会显著偏小，可能需要按月分区
或写入时合并。

不同频率的因子可能需要不同的分区粒度，这也是要实测的一部分。

#### 排序键

这里有真实冲突，两类都是高频查询：

| 排序键 | 友好场景 | 不友好场景 |
|---|---|---|
| `(feature_key, asset_id, event_dt)` | 单因子长区间（因子评价、IC 序列） | 全因子截面 |
| `(event_dt, asset_id, feature_key)` | 全因子截面（组合构建、训练矩阵） | 单因子长区间 |

候选解：择一并依赖 row group 的 min/max 统计兜底；或对热点访问路径做双
物化（同一份数据两种排序，存储翻倍换查询性能）。实测后决定。

#### 压缩与索引

zstd 各级别与 snappy 的读写权衡；是否对 `asset_id`、`feature_key` 启用
bloom filter。

### 判据

固定为三项，不以任何单一指标定胜负：

1. **三类代表性查询的 P50/P95 时延**
   - 单因子长区间：一个 `feature_key`，10 年日频，全市场
   - 全因子截面：某一天，全部 `feature_key`，全市场
   - 训练矩阵构建：200 个 `feature_key`，5 年，指定股票池
2. **存储占用**：总字节数与文件数量
3. **增量写入成本**：单日新增因子值的写入耗时，含 compaction

benchmark 脚本与结论 ADR 一起作为 P1 交付物。脚本保留在仓库里，因为数据量
增长后需要重跑。

## 长表到宽表的查询方式

跨因子分析由 DuckDB pivot 完成：

```sql
-- 示意：某日全因子截面
PIVOT (
  SELECT asset_id, feature_id, value
  FROM read_parquet('var/lake/feature/**/*.parquet')
  WHERE event_dt = $event_dt
    AND knowledge_dt <= $as_of
    AND definition_version = ... AND param_hash = ...
) ON feature_id USING first(value)
```

注意 `knowledge_dt <= $as_of` 是必需的，不是可选优化。读取接口层面不提供
不带 `as_of` 的路径。

## 与旧仓的迁移关系

因子值属于「可以重算的派生数据」，因此**不从 `wx2` 迁移**，在新链路重建，
完成后与旧库交叉校验，差异需有解释。判定标准见
[../migration/wx2-disposition.md](../migration/wx2-disposition.md)。
