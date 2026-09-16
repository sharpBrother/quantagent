---
title: ingest 层职责
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/ingest/
  - db/migrations/src/
---

# ingest：外部源到 PG 研究数据面

## 负责

- **采集**：Wind、Tushare、聚源 JYDB、朝阳永续、宏观源（FRED、金十、WGC）。
  每个源一个子模块，负责游标推进、增量窗口、限流与重试。
- **写入 PG `src_*`**：源原生结构表。**这是全仓库唯一允许写 PG 研究数据面
  的层。**
- **批次登记**：写 `src_<source>._batch`（拉取窗口、源端游标位点、行数、
  digest、成功或失败原因）。
- **版本快照归档**：原始拉取结果 append-only 落
  `var/lake/_vintage/<source>/<dataset>/batch_dt=.../`。

## 不负责

| 排除项 | 正确归属 |
|---|---|
| 标准化（字段改名、单位换算、类型规整） | `lake` 的 std 层 |
| 口径对齐、派生计算 | `lake` 的 mart 层及以上 |
| PIT 判定 | `domain.pit`，且规则声明在 `contracts/visibility/` |

## 允许依赖

`platform`、`contracts`、`adapters`。

## 硬约束

### 原生即原生

源表字段名、类型、语义与源端严格一致。**不改含义、不加业务字段。** 系统侧
信息只走技术元数据列：`_batch_id`、`_ingested_at`、`_row_hash`。

理由：一旦在采集层做了加工，就无法回答「源端到底给了什么」。而这个问题在
排查口径差异时是第一个要问的。

### 写入保护（来自 AGENTS.md，不可删除）

1. 写库函数的 `write_db` 默认 `False`，必须显式 `--write-db` 才真写；
   同时 `QUANTAGENT_ALLOW_DB_WRITE` 必须为 true。
2. 目标表白名单写死在代码常量里，明确禁写的表要有显式拦截。
3. SQL 动词白名单：禁止 `UPDATE` / `MERGE` / `TRUNCATE` / `DROP` / `ALTER`，
   默认 insert-only。
4. 不覆盖既有行：遇到目标键已有行就报错退出，要替换必须显式传参指定范围。
5. 写后回读：同一事务内回读比对行数与 digest，不一致立即回滚。
6. 事务状态未知不重试：提交或回滚结果不确定时停下报告。

这些是写入函数的内建行为，不依赖任何授权流程或身份校验。

### 采集时间不是 PIT

`_ingested_at` 只记录本系统何时取得数据。它**不是**来源发布时间，也不是
可见日。存量数据一次性迁入时 `_ingested_at` 全部等于迁移日，用它做 PIT
等于伪造历史。见 [../../domain/temporal-semantics.md](../../domain/temporal-semantics.md)。

## 典型反例

- **两个 ETL 写同一张表**。旧仓 `fut_holding` 被 `tushare_data.py` 和
  `wind_to_sql_2.py` 双写，两边口径不同且无人知道哪次覆盖了哪次。每张目标
  表必须有唯一的写入者。
- **运行时建表**。旧仓 `factors/daily_factor.py` 用 `if not exists ...
  CREATE TABLE` 在运行时建表，导致表结构没有单一定义处、变更不可追溯。
  结构变更只走 `db/migrations/src/`。
- **在采集脚本里做业务加工**。旧仓 `wind_to_sql_2.py` 既拷贝源表又派生
  `trade_cal`、`stock_ratio`、`market_heat_*`，采集和计算混在一起，导致
  重跑采集会连带重算派生，且派生逻辑无法单独测试。
- **监控表拼写错误且无主键**。旧仓 `task_moniter` 是 `to_sql(append)` 无
  约束写入。运行状态属于 `ops_*` 控制状态面，且必须有主键。
- **爬虫混入生产链路**。旧仓 `crawler/` 多数写 csv 或打印，注释里写明权威
  在别处，但目录结构上看不出来。非生产采集不进 `ingest`。

## 对应的机械检查

- import-linter `分层方向单向`。
- `tests/unit/ingest/`：写入保护的六条约束逐条有测试（默认不写、白名单
  拦截、动词拦截、覆盖检测、回读比对、状态未知不重试）。
