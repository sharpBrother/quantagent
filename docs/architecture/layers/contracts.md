---
title: contracts 层职责
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/contracts/
  - docs/contracts/
---

# contracts：可执行契约

## 负责

- **数据集 schema**：`schemas/pg/`（源原生表）、`schemas/ops/`（控制状态
  表）、`schemas/lake/`（std / mart / feature / model / signal / portfolio）、
  `schemas/publish/`（发布 JSON）。用 pandera 描述 DataFrame，用 pydantic
  描述 JSON 与配置。
- **可见性规则**：`visibility/` 下的声明式 PIT 规则 YAML，以及它们的加载与
  校验。
- **时间形态声明**：每个数据集的 `temporal_kind`、键定义、PIT 等级与
  `pit_from`。
- **跨层读取声明**：资产的 `reads:` 列表，供血缘图消费。

## 不负责

| 排除项 | 正确归属 |
|---|---|
| 规则的**求解**（给定 `as_of` 算出可见行） | `domain.pit` |
| 读取数据、执行 SQL、任何 IO | `adapters` |
| 数据的物理布局（分区、文件大小） | `lake` |

契约只描述「形状与语义是什么」，不实现「怎么拿到」和「怎么算」。

## 允许依赖

`platform`。

## 典型反例

- **把契约写成文档**。旧仓 `docs/data_dictionary/` 有 318 张表的字典，是
  markdown，无法在 CI 中执行，因此无法阻止实现漂移。这一层存在的全部意义
  就是让契约可执行。
- **在契约里连数据库取元信息**。契约必须是静态可读的，否则 CI 无法在没有
  数据库的环境里校验它。import-linter 有一条 `contracts 不做 IO` 专门拦这个。
- **schema 与实现分别演进**。改了 Parquet 的列却不改 schema，或反之。契约
  变更流程见 [../../contracts/README.md](../../contracts/README.md)。
- **用采集时间伪造发布时间**。契约里 `published_at` 缺失就必须是 `NULL`，
  不允许填充成 `_ingested_at`，也不允许在 schema 里给它默认值。

## 对应的机械检查

- import-linter `contracts 不做 IO`：禁止 import `psycopg`、`sqlalchemy`、
  `duckdb`。
- `tests/contracts/`：schema 自洽性、visibility 规则的 YAML 结构校验、
  每个 lake 数据集是否都有对应的可见性规则（缺规则 fail-closed）。
