---
title: platform 层职责
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/platform/
---

# platform：技术基础设施

## 负责

- **配置解析与环境切换**：读取环境变量，用 pydantic-settings 校验，按
  `QUANTAGENT_PROFILE` 切换 `local` / `office` 档位。缺失必填项即启动失败。
- **路径解析**：从 `QUANTAGENT_VAR_ROOT` 出发解析所有本地路径。任何代码都
  不允许自己拼绝对路径。
- **连接工厂**：PostgreSQL 连接与连接池。**全仓库唯一持有凭据的地方。**
- **DuckDB 会话管理**：创建会话、挂载 Parquet、设置内存与线程参数。
- **结构化日志**：统一格式，带 `run_id` 上下文。
- **运行记录（run log）**：每次会写库或产出研究结论的运行落一份 JSON——
  输入 digest、输出 digest、行数、耗时、成功或失败原因、实际执行的 DML 条数。
  目的是三个月后能复现。
- **身份与 digest**：内容哈希、配置 digest、`run_id` 生成。统一算法，避免
  不同模块用不同哈希方式导致身份对不上。

## 不负责

| 排除项 | 正确归属 |
|---|---|
| 任何业务口径（PIT、复权、交易日历） | `domain` |
| 数据 schema 定义 | `contracts` |
| SQL 的业务含义、表名、字段映射 | `adapters` |
| 采集逻辑 | `ingest` |

判断标准：如果一段代码需要知道「什么是交易日」或「哪张表存行情」，它就不
属于 `platform`。

## 允许依赖

标准库与第三方库。**不得 import 本仓库任何其他层。** `platform` 是依赖图的
底座。

## 典型反例

- **在 `platform` 里写 PIT 过滤**。旧仓 `dbconnect.py` 有 31K，混了连接
  管理、批量写入、JDBC 桥接和 `[wx2]` 硬编码，成了什么都往里塞的地方。
  `platform` 必须保持「不知道任何业务」。
- **写死本机路径**。旧仓 `dbconnect.py` 里有 DBeaver JDBC jar 路径和
  `miniforge3/envs/py39arm` 的 JVM 路径，换机器就崩；88 个 py 文件出现
  `/Users/le`。新仓所有路径经 `platform` 解析，ruff 的 `PTH` 规则辅助拦截。
- **硬编码目标库名**。旧仓 `jdbc_batch_insert` 把 `[wx2]` 写进 SQL 模板，
  换库会静默写错地方。库名必须来自配置。
- **硬编码告警接收人与内网 IP**。旧仓的企业微信发送器写死了
  `172.18.62.252:8000` 和接收人工号。这类参数进配置。

## 对应的机械检查

- import-linter `分层方向单向`：`platform` 是最底层，任何指向它的依赖都合法，
  它指向任何层都非法。
- 禁止凭据入库：pre-commit 与 CI 都会拦 `config.ini` 与 `.env`。
