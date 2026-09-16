---
title: lake 层职责
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/lake/
---

# lake：Parquet 物化与读取

## 负责

- **std 物化**：把 PG `src_*` 标准化——统一资产标识、单位、字段命名与
  类型，统一空值语义与时区。**不做业务口径加工。**
- **mart 物化**：口径对齐，产出可分析事实表（行情、财务、成分、持仓、宏观
  序列、基础信息）。口径来自 `domain`，本层只执行。
- **物理布局**：分区键、目标文件大小、排序键、压缩参数、compaction 与小
  文件合并。
- **读取入口**：`readers/` 提供 DuckDB 之上的读取封装（被
  `adapters.lake` 使用）。

## 不负责

| 排除项 | 正确归属 |
|---|---|
| 因子计算 | `features` |
| 模型、信号、组合 | `models` / `strategy` / `portfolio` |
| 口径的**定义** | `domain`。本层只执行 |
| 写 PG | `ingest` |

`std` 与 `mart` 的分界值得写清楚：**改名、换单位、统一类型属于 std；需要
知道业务含义才能做的事属于 mart。** 例如把 `S_INFO_WINDCODE` 改名为
`asset_id` 是 std；把多个源的行情按优先级合并成一份权威行情是 mart。

## 允许依赖

`platform`、`contracts`、`domain`、`adapters`。

## 典型反例

- **在 std 层做业务判断**。std 一旦引入口径判断，就无法回答「标准化之后、
  加工之前的数据长什么样」，排查口径问题时失去中间锚点。
- **物化目标由调用方临时决定**。写哪层、写哪个分区必须由资产定义决定，不能
  由运行时参数随意指定，否则血缘不可信。
- **分区键拍脑袋定**。物理布局参数以 P1 benchmark 的结论 ADR 为准，见
  [../feature-storage.md](../feature-storage.md)。尤其 `feature_id` 不进分
  区键——全A 约 5500 只乘 200 个因子，按 `(dt, feature_id)` 双层分区会碎成
  KB 级小文件。
- **持久化 `.duckdb` 文件**。那会产生第二个事实源，需要独立的备份与迁移
  方案。DuckDB 只做会话级查询引擎。
- **把可重算的物化结果入 git**。旧仓 `data_registry/` 389M 全量入库、
  `reports/` 1.3G，`.gitignore` 不得不开 110 条 `reports/` 例外。`var/`
  整体 gitignore，能重算的一律不入库。

## 对应的机械检查

- import-linter `分层方向单向`。
- `tests/contracts/`：每个 lake 数据集是否有对应的 schema 与可见性规则；
  缺规则即 fail-closed。
- `tests/integration/`：物化的幂等性与分区正确性。
