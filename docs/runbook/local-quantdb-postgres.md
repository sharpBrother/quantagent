---
title: QuantDB 挂载与 PostgreSQL 启停
status: active
created: 2026-11-14
updated: 2026-11-14
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
