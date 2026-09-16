---
title: 旧仓代码模块处置清点
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - docs/migration/roadmap.md
  - src/quantagent/
---

# 旧仓代码模块处置清点

范围：`pycharm_workspace` 的**代码模块**。数据表见
[../migration/wx2-disposition.md](../migration/wx2-disposition.md)，文档与
制品见 [../migration/docs-and-artifacts-disposition.md](../migration/docs-and-artifacts-disposition.md)。

## 处置类别

| 类别 | 含义 |
|---|---|
| **移植** | 逻辑基本保留，适配新分层与端口 |
| **提炼** | 保留口径与测试，替换实现。先用 golden test 固化旧行为 |
| **重写** | 只保留需求，实现从头写 |
| **丢弃** | 不进新系统，留旧仓追溯 |

「提炼」是本次迁移的主要手法。它与「移植」的区别：移植保留代码结构，提炼
只保留行为契约。口径类模块一律走提炼，因为它们的价值在口径而不在实现。

## 清点表

按旧仓 py 文件数排序。

| 旧模块 | 规模 | 处置 | 依据与去向 |
|---|---|---|---|
| `legacy/` | 693 | **丢弃** | 28.5 万行，零引用。已被现役模块取代 |
| `tests/` | 428 | **部分提炼** | 口径类测试提炼进 `tests/golden/`；24 个 `test_task0441_*` 这类一次性验收测试丢弃 |
| `scripts/` | 300 | **重写** | 仅约 8% 是长期入口。逐条重写为 CLI 子命令或 Dagster asset，不迁移脚本本身 |
| `alpha_factory/` | 142 | **提炼** | 长表模式与 `group_backtest` 的分组收益语义是核心资产。因子实现移植到 `features/library/`，分组收益到 `strategy/backtest/vectorized/`，`factor_math.py` / `preprocessing.py` 的 WLS 到 `models/estimators/linear/`，`etf/gateway.py` 口径抽为契约测试 |
| `etf_sector_rotation/` | 96 | **提炼** | 行业轮动口径保留；`EtfStrategy` 的回测路径收敛到 `strategy/backtest/rebalance/`；观点组织到 `agents/sector/` |
| `strategy_engine/` | 78 | **提炼** | `BacktestEngine` 的账户、成交、成本、调仓语义是 `rebalance` 内核的来源。`adapters/` 包装层丢弃——新仓策略直接实现统一接口 |
| `macro_regime/` | 36 | **提炼** | 宏观状态判定口径保留到 `agents/macro/`；`pit.py` 的可见性逻辑提炼为 `contracts/visibility/` 规则 + `domain/pit` 实现 |
| `agent_style_rotation/` | 32 | **提炼** | 行业评分表生产归 `features/`，`price_cluster.py` 的层次聚类归 `models/estimators/`，观点组织归 `agents/style/` |
| `style_rotation/` | 30 | **提炼** | 成长价值与大小盘策略归 `strategy/signals/`。与 `agent_style_rotation/` 名字相似但职责不同，新仓按职责分开而非按名字合并 |
| `data/` | 30 | **重写** | ETL 脚本。重写为 `ingest/sources/` 下的采集器。`wind_to_sql_2.py` 的采集与派生混合要拆开；`情绪择时推送.py` 等中文文件名一并规范 |
| `multi_asset/` | 23 | **提炼** | 风险预算与 views 的口径保留到 `portfolio/construct/`。与 `enhanced_optimizer/`、`portfolio_engine/` 三者职责重叠，收敛为一套 |
| `strategy/` | 20 | **分别定性** | `generic_backtest_framework.py` 行为对照后定去留；十余个 `*_backtest.py` 是入口脚本，重写为 CLI 子命令；`可转债套利.py` 等一次性脚本逐个判定 |
| `factors/` | 18 | **提炼** | 因子逻辑移植到 `features/library/`；`stock_<factor>` 运行时建表模式丢弃，统一为长表 |
| `enhanced_optimizer/` | 18 | **提炼** | `risk_parity.py` 的 scipy 风险平价保留到 `portfolio/construct/`；`data/gateway.py` 口径抽为契约测试 |
| `gold_timing/` | 14 | **提炼** | 黄金择时口径保留到 `agents/gold/` |
| `research_release_guard/` | 13 | **提炼** | 研究发布边界校验的思路保留，实现并入 `contracts/` 的可执行校验与 `tests/contracts/` |
| `portfolio_engine/` | 11 | **丢弃** | 生产消费者几乎只有 `agent_risk_monitor/export.py`。能力并入 `portfolio/` |
| `sandbox/` | 10 | **丢弃** | 实验代码。有价值的结论提炼进 `docs/research/` |
| `bond_timing/` | 10 | **提炼** | 债券择时口径保留到 `agents/bond/`。注意其冻结 bundle 是发布必需输入，须迁 `frozen/` |
| `task_scheduler/` | 9 | **重写** | 自研调度器。重写为 Dagster asset/job/schedule。`jobs.json` 的任务清单作为对应关系的输入 |
| `reports/` | 9 | **丢弃** | 报告生成脚本。发布装配重写为 `publish/builders/` |
| `tq/` | 8 | **丢弃** | 明确丢弃项 |
| `core/` | 8 | **提炼** | 最重要的提炼对象。`data_gateway_base.py` 拆为 `domain/ports` + `domain/pit` + `adapters`；`universe_provider.py` 拆为 `domain/universe` + `UniverseRepository`；`market_data_service.py`（2804 行）按数据类型拆到多个 Repository；`raw_loader.py` 丢弃（字符串拼 SQL 且无 PIT） |
| `crawler/` | 7 | **丢弃** | 非生产采集，多数写 csv 或打印，注释已注明权威在别处 |
| `agent_risk_monitor/` | 4 | **重写** | 只有测试引用。风控 Agent 在 `agents/risk/` 重写 |
| `agent_common/` | 3 | **丢弃** | 薄守卫层，新架构由 `agents/base/` 承担 |
| `website/` | 前端 | **移植** | 132 个 ts/tsx/js/css、约 2 万行迁 `apps/web/`。保留 loader 的 schema 校验与 Playwright e2e；已停用的页面不迁 |
| `integration/` | 2 | **丢弃** | 明确丢弃项 |
| `tool/` | 1 | **丢弃** | 明确丢弃项 |
| `factor_testing/` | 0 | **丢弃** | 明确丢弃项 |
| `qualification/` | 0 | **丢弃** | 明确丢弃项 |
| `dbconnect.py`（根） | 单文件 | **重写** | 混了连接管理、批量写入、JDBC 桥接与硬编码 `[wx2]`。重写为 `platform/storage/` 与 `adapters/postgres/`，JDBC 相关内容随 SQL Server 一并消失 |
| `migrations/` | 0 | **丢弃** | 空目录 |

## 明确丢弃的模块清单

作为单条规则记录，便于核对：`legacy/`、`factor_testing/`、`tq/`、
`sandbox/`、`tool/`、`qualification/`、`integration/`、`crawler/`（非
生产）、`portfolio_engine/`、`agent_common/`、`reports/`，以及 `scripts/`
中的一次性脚本。

**文档与制品不在此列**，一律按内容逐项定性，见
[../migration/docs-and-artifacts-disposition.md](../migration/docs-and-artifacts-disposition.md)。

## 提炼类模块的操作手法

固定四步，不可简化：

1. **取快照**：用旧库真实数据生成 fixture，落 `tests/fixtures/`。必须覆盖
   边界情形——停牌、退市、代码复用、报告期跨年、非交易日端点。
2. **固化旧行为**：把旧实现在该快照上的**现有输出**写成期望值。此时不判断
   对错，只记录事实。
3. **新实现对拍**：新实现跑同一套 fixture，输出必须逐值一致。
4. **差异必须有解释**：判定是新实现有 bug 还是旧实现有 bug。前者修代码；
   后者修正期望值、在 `docs/adr/` 记一页说明原因，然后更新基线。**不允许
   静默改基线。**

这是 P3 的验收手段，也是避免「重构顺手改了口径」的唯一可靠办法。口径漂移
是重构中最危险的错误，因为它不报错、不崩溃，只是让所有历史结论悄悄失效。

## 清点的维护

本表是活文档。每个模块处置完成后在这里标注完成，不另建台账。发现处置判定
需要修改时直接改本表，并在 `docs/adr/` 记录原因（如果原因是口径层面的）。
