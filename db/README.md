---
title: db 数据库迁移
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - db/
  - src/quantagent/adapters/postgres/
---

# db：PostgreSQL 结构演进

PostgreSQL 上有两个互不混用的逻辑面，因此迁移也分开演进：

| 目录 | 面 | schema 前缀 | 写入者 |
|---|---|---|---|
| `migrations/src/` | 研究数据面 | `src_wind`、`src_tushare`、`src_jydb`、`src_suntime`、`src_macro` | 只有 `quantagent.ingest` |
| `migrations/ops/` | 控制状态面 | `ops_*`（含 Dagster 运行存储） | 编排与 platform.runlog |

分开的理由：两者的变更频率、风险等级和回滚策略完全不同。源表结构跟随外部
源变化，控制状态表跟随编排能力变化，混在一条迁移序列里会让「改调度表」和
「改源镜像」互相阻塞。

## 约束

1. **研究数据面只存源原生结构**。字段名、类型、语义与源端严格一致，不改
   含义、不加业务字段。系统侧信息只走 `_batch_id` / `_ingested_at` /
   `_row_hash` 技术元数据列与旁表 `src_<source>._batch`。
2. **派生数据不进 PG**。因子、信号、组合、回测结果全部落 Parquet。
3. **控制状态面不对 lake 供数**，任何研究查询都不得读取 `ops_*`。
4. **迁移只前进**。不写破坏性的 `DROP` / `ALTER` 回退脚本；需要撤销时新增
   一条前向迁移。
5. **不在迁移里写数据**。`seeds/` 只放静态参照数据（交易所日历种子、行业
   分类码表这类），且必须可重复执行。

第一批源镜像清单见 [`src_tables.yaml`](src_tables.yaml)，口径说明见
[`../docs/contracts/src-plane.md`](../docs/contracts/src-plane.md)。

## 命令

```
quantagent db status
quantagent db migrate --plane all          # 干跑，打印 pending
quantagent db migrate --write-db           # 真正执行；还需 QUANTAGENT_ALLOW_DB_WRITE=true
```

两条序列独立。登记表 `qa_migrate.applied` 由运行器创建，不进编号 SQL。
未同时打开写闸时 `migrate` 拒绝执行。

`ddl/` 存放供人阅读的当前结构快照，由迁移生成，不手工维护。
