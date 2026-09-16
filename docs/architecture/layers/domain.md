---
title: domain 层职责
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/domain/
---

# domain：口径规则，零存储依赖

这一层是整个架构里最需要保护的部分。口径一旦被污染，所有下游结论都不成立，
而污染往往是无声的。

## 负责

| 子模块 | 职责 |
|---|---|
| `calendar/` | 交易日历、频率对齐、T+N 推算、区间切分 |
| `adjust/` | 复权规则：复权方式、复权因子的应用口径 |
| `identity/` | 资产身份：代码映射、上市退市生命周期、代码复用消歧、跨源代码对齐 |
| `pit/` | 可见性规则求解：给定数据集规则与 `as_of`，算出哪些行可见 |
| `universe/` | 股票池构造规则：成分、过滤条件、生效区间 |
| `classification/` | 行业与风格分类口径 |
| `ports/` | 读取接口 Protocol 定义 |

## 不负责

| 排除项 | 正确归属 |
|---|---|
| 连接、分块、重试、谓词下推、分区裁剪 | `adapters` |
| 文件布局、SQL 生成 | `adapters` / `lake` |
| 因子计算 | `features` |
| schema 定义 | `contracts` |

## 允许依赖

`contracts`，以及标准库与数值库（numpy、pandas 的纯计算部分）。

## 硬约束：零存储依赖

**不得 import 任何 PostgreSQL、DuckDB、Parquet、pandas IO 相关内容。**

验证标准很具体：`tests/unit/domain/` 下的全部测试必须在没有数据库连接、
没有任何文件的条件下通过。如果某个规则测试需要先起一个 PG 或准备一个
Parquet 文件，说明这段逻辑放错了层。

理由不只是可测性。口径规则的正确性是研究结论成立的前提，而它的正确性只能
靠穷举边界情形来验证——停牌日、退市日、代码复用日、报告期跨年、非交易日
落在区间端点。这些情形在真实数据里可能几年才出现一次，必须用构造数据测，
而构造数据的成本必须足够低。

## 典型反例

- **规则与传输绑死**。旧仓 `core/data_gateway_base.py` 的 `BaseDataGateway`
  同时承担 PIT 原语（`latest_visible_by_key`）、死锁重试和 IN 分块，且自身
  `from dbconnect import DBConnect`。结果是 PIT 逻辑无法脱离数据库测试，
  也无法在换存储时复用。新仓把它拆成 `domain/pit` 的规则 + `domain/ports`
  的接口 + `adapters` 的传输。
- **在 port 接口里暴露 SQL 或表名**。接口签名出现 `table_name: str` 或
  `where_clause: str` 就已经破坏了抽象。判断标准：把底层从 PostgreSQL 换成
  Parquet，接口签名不应有任何变化。
- **每个研究线各自实现一遍口径**。旧仓有 `alpha_factory/etf/gateway.py`、
  `macro_regime/pit.py`、`enhanced_optimizer/data/gateway.py` 等多套网关，
  PIT 与股票池口径在各处重复实现，差异无人知晓。口径只能有一处定义。
- **在读取时才做 PIT 过滤且不声明规则**。旧仓的 PIT 是读取时用
  `ROW_NUMBER() OVER (...) WHERE visible_col <= as_of` 实现的，规则散在
  SQL 里，无法枚举、无法审查、无法判断某个数据集到底用了哪条规则。新仓的
  规则是声明式 YAML，`domain/pit` 只做求解。
- **允许无 `as_of` 的读取路径存在**。只要存在一条不传 `as_of` 的便捷读取
  接口，它就一定会被用在需要 PIT 的地方。接口层面不提供这条路。

## 对应的机械检查

- import-linter `domain 是纯规则层，禁止绑定任何存储实现`：禁止 import
  `adapters`、`ingest`、`lake`、`psycopg`、`sqlalchemy`、`duckdb`、`pyarrow`。
- import-linter `业务层不得依赖 composition root`：`domain` 不得 import
  `cli` 或 `orchestration`。
- `tests/unit/domain/` 标记为 `unit`，CI 中在无外部依赖的环境运行。
