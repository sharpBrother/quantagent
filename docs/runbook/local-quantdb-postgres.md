---
title: QuantDB 挂载与 PostgreSQL 启停
status: active
created: 2026-11-14
updated: 2026-11-18
applies_to:
  - .env.example
  - src/quantagent/cli/db.py
  - orchestration/launchd/
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

## Mac Dagster daemon（launchd）（2026-11-18）

launchd 只托管 `dagster-daemon`，不启动 PostgreSQL。PG 仍按上文手动启动。启动脚本
等外接盘和 PG 就绪，各最多等 10 分钟，超时以退出码 75 结束，launchd 每 60 秒重试。

文件分工：

- `orchestration/launchd/com.quantagent.dagster-daemon.plist.template`：仓库里的模板，
  占位符为 `__REPO__`、`__VAR_ROOT__`、`__HOME__`。
- `$VAR_ROOT/run-dagster-daemon-mac.sh`：启动脚本，不进 git。它把
  `orchestration/dagster.yaml` 同步到 `$DAGSTER_HOME/dagster.yaml`，生成
  `$DAGSTER_HOME/workspace.yaml`，然后 `exec uv run dagster-daemon run --workspace ...`。
  同步时若旧文件内容不同，先改名为 `*.bak.<时间戳>`。
- 写库闸 `QUANTAGENT_ALLOW_DB_WRITE=true` 只在 plist 的 `EnvironmentVariables` 里。
  交互会话读的是仓库 `.env`，仍默认不写库。

安装（由 `leo` 在执行机上运行）：

```bash
REPO=/Users/leo/Projects/quantagent
VAR_ROOT=/Volumes/QuantDB/quantagent/var
PLIST=~/Library/LaunchAgents/com.quantagent.dagster-daemon.plist

mkdir -p "$VAR_ROOT/logs" ~/Library/LaunchAgents
sed -e "s|__REPO__|$REPO|g" -e "s|__VAR_ROOT__|$VAR_ROOT|g" -e "s|__HOME__|$HOME|g" \
  "$REPO/orchestration/launchd/com.quantagent.dagster-daemon.plist.template" > "$PLIST"
plutil -lint "$PLIST"
launchctl bootstrap gui/$(id -u) "$PLIST"
```

日常操作：

```bash
# 改了仓库代码或 dagster.yaml 后重启（脚本会重新同步配置）
launchctl kickstart -k gui/$(id -u)/com.quantagent.dagster-daemon

# 卸载。bootout 后 launchd 不再拉起；要删除的话再删 plist
launchctl bootout gui/$(id -u)/com.quantagent.dagster-daemon
rm "$PLIST"
```

日志：

- `~/Library/Logs/quantagent/dagster-daemon.out.log`：脚本的时间戳阶段行与 daemon 标准输出。
- `~/Library/Logs/quantagent/dagster-daemon.err.log`：标准错误。日志不放外接盘：launchd 先打开日志再启动进程。
- `$DAGSTER_HOME/logs/event.log`：Dagster 自身事件日志。

核验：

```bash
launchctl print gui/$(id -u)/com.quantagent.dagster-daemon | grep -E 'state|pid|last exit'
pgrep -fl dagster-daemon
# daemon_heartbeats 每个 daemon 一行，timestamp 应在最近几十秒内
sqlite3 "$DAGSTER_HOME/history/runs.db" 'SELECT daemon_type, timestamp FROM daemon_heartbeats;'
```

若 `history/runs.db` 不存在，用 `find "$DAGSTER_HOME" -name runs.db` 确认实际位置。

外接盘未挂载时，脚本在等待阶段以 75 退出，launchd 每 60 秒重试。盘未挂载时 launchd
也无法打开 `$VAR_ROOT/logs/` 下的日志文件，因此这段时间进程可能根本没有启动，
挂载后会自动启动。`logs/` 目录须在首次 `bootstrap` 前存在，这就是安装步骤里 `mkdir -p` 的原因。

旧的 `$DAGSTER_HOME/dagster.yaml` 是 PG 运行存储模板。首次运行脚本时它会被改名为
`dagster.yaml.bak.<时间戳>` 并替换为 SQLite 版本。`$DAGSTER_HOME/storage/` 不受影响。

**macOS 权限（必须）**：launchd 拉起的进程读外接盘会报 `Operation not permitted`（TCC 拦截，退出码 126）。
在“系统设置 → 隐私与安全性 → 完全磁盘访问权限”加入 `/bin/bash` 与
`~/.local/share/uv/python/cpython-3.12.15-macos-aarch64-none/bin/python3.12`（uv 管理的解释器，升级小版本后路径会变，需重新授权）。
