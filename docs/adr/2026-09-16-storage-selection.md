---
title: 存储选型：PostgreSQL + Parquet + DuckDB
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/adapters/
  - src/quantagent/lake/
  - db/
supersedes: null
superseded_by: null
---

# 存储选型：PostgreSQL + Parquet + DuckDB

## 背景

旧仓用 SQL Server（库名 `wx2`）承载全部数据：源镜像、派生因子、策略结果、
调度日志。暴露出来的问题：

- **跨平台驱动困境**：macOS 上通过 JDBC 桥接连接，`dbconnect.py` 里写死了
  DBeaver 的 jar 路径与 `miniforge3/envs/py39arm` 的 JVM 路径。仓库里留下
  12 个 JVM 崩溃日志。
- **Python 版本被锁**：为了驱动兼容停在 3.8/3.9，而 136 个文件已经在用
  PEP585 泛型。
- **表设计低效**：一因子一表造成表爆炸，跨因子 JOIN 昂贵，需事后补覆盖
  索引；`to_sql(append)` 无约束写入。
- **分析型查询不适配**：行存数据库做大范围截面扫描代价高。

同时，研究场景的特点是：**单机、只读为主、大范围扫描、需要可迁移**。

## 决策

按数据的性质分三处：

| 用途 | 选型 |
|---|---|
| 源数据原生镜像 | PostgreSQL，`src_*` schema |
| 控制状态（调度、水位、运行日志） | PostgreSQL，`ops_*` schema |
| 派生事实（std / mart / feature / model / signal / portfolio） | Parquet，落 `var/lake/` |
| 查询引擎 | DuckDB，不持久化 `.duckdb` |
| 冻结输入制品 | `frozen/`，入 git |
| 发布产物 | `publish/`，入 git |

## 理由

**PostgreSQL 承载源镜像**：源数据需要事务、约束、唯一键和跨表查询，这些是
关系库的强项。psycopg3 是纯 Python 实现（binary 包带预编译 libpq），不需要
ODBC 驱动、不需要 JDBC 桥接、不需要 JVM，macOS 与 Windows 行为一致。这直接
解掉了 Python 版本被驱动锁死的问题。

**Parquet 承载派生事实**：列存 + 分区裁剪对"取 200 个因子 5 年数据"这类
查询有量级优势。更重要的是**可迁移**——Parquet 是开放格式，换查询引擎不用
迁数据。派生数据的特点是可重算，因此不需要数据库的事务保证。

**DuckDB 作查询引擎**：零运维，原生读 Parquet，单机性能足够，SQL 方言接近
标准。不持久化 `.duckdb` 文件是刻意的——见"推论"。

## 被否方案

| 方案 | 否决理由 |
|---|---|
| 继续用 SQL Server | 跨平台驱动困境不可解，且锁死 Python 版本 |
| 全部放 PostgreSQL（含派生） | 行存做大范围截面扫描代价高；且会复刻 `wx2` 的混层问题 |
| 全部放 Parquet（含源数据） | 源数据需要唯一键约束与事务，Parquet 没有；增量更新与去重实现成本高 |
| ClickHouse / Doris | 单人维护的项目引入分布式 OLAP 是过度设计，运维成本不成比例 |
| DuckDB 作唯一存储（持久化 `.duckdb`） | 会产生第二个事实源，需要独立的备份、迁移、并发方案；且失去 Parquet 的可迁移性 |
| Delta Lake / Iceberg | 表格式带来的事务与时间旅行能力，在单人单机只读为主的场景收益小于运维成本 |

## 代价

1. **三处存储意味着三套读取路径**。由 `adapters` 的三套实现吸收，但这是
   真实的复杂度增加。
2. **Parquet 没有约束保证**。数据正确性完全依赖写入时的契约校验，如果校验
   有漏洞，脏数据会直接落盘。
3. **跨存储 JOIN 需要显式处理**。源表在 PG、派生在 Parquet，需要同时读两处
   的查询要么先物化一侧，要么用 DuckDB 的 postgres 扩展。
4. **DuckDB 不持久化意味着每次会话有挂载开销**。对交互式分析有轻微影响。
5. **Parquet 的小文件问题需要主动管理**。compaction 是运维项，不是自动的。

## 推论

1. **DuckDB 不持久化 `.duckdb` 文件**。理由：一旦持久化就变成第二个事实
   源，需要自己的备份与迁移方案，而它提供的索引与事务在单机只读分析场景
   收益有限。保持 Parquet 为唯一事实源，DuckDB 随时可替换。
2. **物理布局待实测**。分区键、文件大小、排序键、压缩参数以 P1 benchmark
   结论为准，在结论出来之前不固化。见
   [../architecture/feature-storage.md](../architecture/feature-storage.md)。
3. **`var/` 整体 gitignore**。派生数据可重算，不入库。
4. **迁移期需要一个只读的 SQL Server 适配器**，仅在 P2 期间用于读取 `wx2`
   存量，迁移完成后删除。
