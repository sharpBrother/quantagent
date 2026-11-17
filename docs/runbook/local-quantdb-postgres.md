---
title: QuantDB 挂载与 PostgreSQL 启停
status: active
created: 2026-11-14
updated: 2026-11-17
applies_to:
  - .env.example
  - src/quantagent/cli/db.py
---

# QuantDB 挂载与 PostgreSQL 启停

本机用 Homebrew PostgreSQL 16 在外接盘 QuantDB 上运行 QuantAgent 专用实例。
研究库 `quantagent` 和控制库 `quantagent_ops` 共用 `127.0.0.1:5433`。
仓库本地 `.env` 提供连接配置，`QUANTAGENT_VAR_ROOT` 指向
`/Volumes/QuantDB/quantagent/var`。专用实例按需手动启动。

## 挂载并启动

1. 接上外接盘。如果访达里没有出现 QuantDB，在「磁盘工具」选中 QuantDB 卷并点击「挂载」。
2. 运行 `diskutil info /Volumes/QuantDB`，确认 `Mounted: Yes`、
   `Mount Point: /Volumes/QuantDB` 和 `Owners: Enabled`。若挂载点不同，先处理挂载问题。
3. 用下面的命令启动。若实例已经运行，跳到连接核验。

   ```bash
   /opt/homebrew/opt/postgresql@16/bin/pg_ctl \
     -D /Volumes/QuantDB/postgresql/data \
     -l /Volumes/QuantDB/postgresql/server.log -w start
   ```

4. 在仓库根目录运行 `uv run quantagent db status`。确认 `pg src` 和 `pg ops`
   均指向 `127.0.0.1:5433`，`var_root` 指向外接盘。启动失败时查看
   `/Volumes/QuantDB/postgresql/server.log`。

## 停止并弹出

先结束正在读写外接盘的 QuantAgent 任务，再停止专用实例。

```bash
/opt/homebrew/opt/postgresql@16/bin/pg_ctl \
  -D /Volumes/QuantDB/postgresql/data -m fast -w stop
```

确认命令返回 `server stopped` 后，在访达弹出 QuantDB，再拔掉硬盘。

## Dagster 运行存储账号 `quantagent_dagster`（2026-11-17）
Dagster 要对 `ops` 里自己的 21 张运行表做增删改查。用专用角色，不给 `quantagent_ingest`
扩权：ingest 只写研究数据面。角色只在控制库 `quantagent_ops` 的 `ops` 上有 DML，
不能建表，研究库 `quantagent` 里没有任何 `src_*` 权限。由 `leo` 执行：
```sql
CREATE ROLE quantagent_dagster LOGIN;
GRANT CONNECT ON DATABASE quantagent_ops TO quantagent_dagster;
GRANT USAGE ON SCHEMA ops TO quantagent_dagster;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ops TO quantagent_dagster;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA ops TO quantagent_dagster;
ALTER DEFAULT PRIVILEGES FOR ROLE leo IN SCHEMA ops
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO quantagent_dagster;
ALTER DEFAULT PRIVILEGES FOR ROLE leo IN SCHEMA ops
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO quantagent_dagster;
```
密码由负责人设置：`ALTER ROLE quantagent_dagster PASSWORD '...';`，执行机 `.env` 填
`QUANTAGENT_PG_OPS_USER=quantagent_dagster` 与 `QUANTAGENT_PG_OPS_PASSWORD`，库名
`quantagent_ops`，主机端口与研究库相同。仓库里不存密码。

## ingest 只读迁移登记表（2026-11-17）
否则 `quantagent db status` 在 ingest 账号下读不到 `qa_migrate.applied`，显示 `applied=0`。
两个库都由 `leo` 执行：
```sql
GRANT USAGE ON SCHEMA qa_migrate TO quantagent_ingest;
GRANT SELECT ON qa_migrate.applied TO quantagent_ingest;
```
