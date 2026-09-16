---
title: adapters 层职责
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/adapters/
  - tests/contracts/
---

# adapters：存储适配器

## 负责

实现 `domain.ports` 的 Protocol，把领域语言的读取请求翻译成具体存储访问。

| 子模块 | 后端 |
|---|---|
| `postgres/` | PG 研究数据面 `src_*` 与控制状态面 `ops_*` |
| `lake/` | Parquet + DuckDB |
| `memory/` | in-memory fake，让业务层单测不需要任何外部依赖 |

传输细节全部在这一层：连接获取与归还、IN 子句分块、死锁与超时重试、谓词
下推、分区裁剪、批量读取的分页游标、列投影。

## 不负责

| 排除项 | 正确归属 |
|---|---|
| 决定 PIT 过滤条件 | `domain.pit` 给出条件，适配器只执行 |
| 决定复权方式、股票池规则 | `domain` |
| 写 PG 研究数据面 | `ingest`（适配器提供写入原语，但只有 ingest 能调） |
| 物化决策（写哪层、分区怎么切） | `lake` |

关键区分：适配器**执行**口径，不**决定**口径。它收到的是已经被
`domain` 解析好的参数，不自行判断业务语义。

## 允许依赖

`platform`、`contracts`、`domain`（为实现其 Protocol）。

## 三套适配器必须行为一致

`tests/contracts/` 下的端口行为契约测试对三套实现跑同一套断言。这不是形式
要求——它是「换存储不改业务」这个承诺的唯一证据。如果 `memory` 与
`postgres` 在空结果、缺列、重复键、时区处理上行为不同，那么用 `memory`
写的单测就不能证明生产路径正确。

`memory` 的存在价值也在这里：它让业务层（`features`、`strategy`、
`portfolio`）的测试可以完全脱离数据库，从而跑得快、跑得全。

## 典型反例

- **业务模块自己建连接**。旧仓 139 个文件直接 `import dbconnect`，其中
  `factors` 12 个、`strategy` 8 个、`strategy_engine` 8 个、
  `agent_style_rotation` 6 个。每一处单独看都能跑，合起来的结果是读边界
  形同虚设、口径无法统一收口。
- **适配器里夹带业务判断**。例如适配器自己决定「行情缺失就取前一交易日」。
  这是口径决策，属于 `domain`；适配器这么做会让同一份规则在不同适配器下
  产生不同结果。
- **字符串拼接 SQL**。旧仓 `core/raw_loader.py` 用字符串拼 SQL 且无 PIT，
  既有注入风险也无法保证口径。参数化查询是唯一允许的方式。
- **在适配器里硬编码库名或 schema 名**。旧仓 `jdbc_batch_insert` 写死
  `[wx2]`。schema 名必须来自配置。
- **只给 postgres 实现、memory 用 mock 糊弄**。mock 不参与契约测试，等于
  没有一致性保证。`memory` 必须是真实的 in-memory 实现。

## 对应的机械检查

- import-linter `分层方向单向`：`adapters` 在 `domain` 之上、`ingest` 之下。
- import-linter `只有 ingest 与 adapters 可以接触 PostgreSQL 驱动`：
  `features` / `models` / `strategy` / `portfolio` / `agents` / `publish`
  禁止 import `psycopg` 与 `sqlalchemy`。
- `tests/contracts/`：三套适配器跑同一套端口行为断言。
