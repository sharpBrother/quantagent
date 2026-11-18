---
title: 源端发布的版本可以落表，与采集批次 vintage 不同
status: active
created: 2026-11-18
updated: 2026-11-18
applies_to:
  - db/migrations/src/
  - src/quantagent/ingest/
supersedes: null
superseded_by: null
---
# 源端发布的版本可以落表，与采集批次 vintage 不同
## 背景
[不做批次 vintage 归档](2026-09-17-no-source-vintage-archive.md) 否决了按采集批次保留拉取快照：
批次号和 `_ingested_at` 不是市场可见时点。ALFRED 的 `realtime_start`、WGC 报告期次、GPR 文件、
金十事件则是源端自己发布的版本，带有源端给出的发布时间。
## 决策（负责人 2026-11-18 确认）
1. 源端提供版本身份与发布时间时，修订按新版本追加，版本身份进主键，旧版本不改不删。
2. 版本的可见日取源端给出的发布时间，可以作为 `source_field` 的依据，等级按证据评定。
3. 源端不提供版本时仍按镜像当前状态处理，不得用批次号或 `_ingested_at` 造版本。
## 后果
FRED 新增版本表，主键含 `realtime_start`。WGC、GPR、金十按各自的版本身份建键。
