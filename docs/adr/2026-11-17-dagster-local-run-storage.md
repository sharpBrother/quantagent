---
title: 执行机上的 Dagster 运行存储改用本地 SQLite
status: active
created: 2026-11-17
updated: 2026-11-17
applies_to:
  - orchestration/dagster.yaml
  - orchestration/resources/wind.py
  - db/migrations/ops/0002_dagster_storage.sql
supersedes: null
superseded_by: null
---
# 执行机上的 Dagster 运行存储改用本地 SQLite
## 背景
Dagster 运行表原先建在 PG 控制库 `ops`（`23d4846`，`0002_dagster_storage.sql`），执行机经 ToDesk
端口转发连到 Mac 上的 PG。2026-11-17 执行机 daemon 的 SCHEDULER、QUEUED_RUN_COORDINATOR、
ASSET 等线程卡在读写心跳的调用里永不返回；Mac 上看 PG 只有 1 条来自执行机的会话、0 个锁等待。
转发吞掉了 daemon 持有的空闲长连接：客户端以为连着，服务端没有会话，任何服务端超时都管不到。
采集任务本身已串行，卡死的是 daemon 自己的常驻连接。
## 决策
1. 执行机 `DAGSTER_HOME` 用 Dagster 默认本地 SQLite 存运行记录、心跳与调度状态，模板去掉 `storage.postgres`。
   排队协调器（`max_concurrent_runs: 1`）保留。
2. 采集步骤在子进程里跑，每页提交后写进度文件；父进程发现 600 秒无新页就终止子进程，这一步失败，
   下一轮从游标续跑。采集连接设 `lock_timeout=60s`，遇到孤儿事务持有同一主键时报错而不是一直等。
3. `ops` 里 21 张 Dagster 表与 `quantagent_dagster` 账号保留不删，暂不使用。
## 代价
- 运行历史只在执行机本地，Mac 上看不到；研究数据与写入记录仍在 PG 与 run log。
- 链路问题没有根治：采集连接被吞时只能靠看门狗终止重试。孤儿会话在 PG 上可能残留，
  需要时由 `leo` 终止。
