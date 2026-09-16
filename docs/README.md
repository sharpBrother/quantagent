---
title: 文档导航
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - docs/
---

# 文档导航

这是唯一的文档入口。旧仓有 `docs/README.md`、`docs/STATUS.md`、
`docs/decisions/README.md`、`docs/legacy/README.md` 四个并行入口，加上根目录
的 `AGENTS.md` / `CLAUDE.md` / `CODEX.md` / `AI_TEAM.md` 四份重叠指针，读者
不知道从哪开始。这里只有一个。

## 先读这三份

1. [../PROJECT.md](../PROJECT.md) — 项目定位、目标、技术约束
2. [../AGENTS.md](../AGENTS.md) — 工作规则、数据安全铁律、研究正确性铁律
3. [CONVENTIONS.md](CONVENTIONS.md) — 文档公约（四类文档、frontmatter、生命周期）

## 架构

| 文档 | 内容 |
|---|---|
| [architecture/overview.md](architecture/overview.md) | 系统全貌、分支式依赖图、设计原则 |
| [architecture/data-layers.md](architecture/data-layers.md) | 数据层职责与允许依赖、PG 双面、Parquet、DuckDB 的边界 |
| [architecture/ports-and-adapters.md](architecture/ports-and-adapters.md) | domain 纯规则、端口 Protocol、三套适配器、旧仓口径继承 |
| [architecture/feature-storage.md](architecture/feature-storage.md) | 因子长表格式、三段身份、训练宽矩阵、物理布局 benchmark |
| [architecture/modeling-extensibility.md](architecture/modeling-extensibility.md) | 建模抽象，线性模型到机器学习的扩展路径 |
| [architecture/backtest-contract.md](architecture/backtest-contract.md) | 回测语义合同、三类内核、合并的验收标准 |
| [architecture/cli-and-orchestration.md](architecture/cli-and-orchestration.md) | 统一 CLI、Dagster 资产化编排、脚本治理 |
| [architecture/layers/](architecture/layers/) | 每层一份职责定义 |
| [architecture/legacy-inventory.md](architecture/legacy-inventory.md) | 旧仓代码模块逐个处置判定 |

## 口径与契约

| 文档 | 内容 |
|---|---|
| [domain/temporal-semantics.md](domain/temporal-semantics.md) | 三条时间轴、四种时间形态 |
| [domain/pit-rules.md](domain/pit-rules.md) | 可见性规则、PIT 等级、因子字段强制要求 |
| [contracts/README.md](contracts/README.md) | 可执行契约与文档的双向绑定、契约变更流程 |
| [contracts/trade-calendar.md](contracts/trade-calendar.md) | 第一个数据集契约：交易日历 |

## 决策记录

[adr/](adr/) — 日期命名，只增不改。当前生效的决策全部在这里，`status:
superseded` 的保留正文供追溯。

## 迁移

| 文档 | 内容 |
|---|---|
| [migration/roadmap.md](migration/roadmap.md) | P0–P6 阶段、验收标准、回滚点 |
| [migration/wx2-disposition.md](migration/wx2-disposition.md) | 旧 SQL Server `wx2` 逐表处置标准 |
| [migration/docs-and-artifacts-disposition.md](migration/docs-and-artifacts-disposition.md) | 旧仓文档与制品逐项处置标准 |

## 运维与研究

- [runbook/](runbook/) — 部署、迁移操作、故障处理
- [research/](research/) — 按研究线的笔记与结论

## 旧仓在哪

旧仓 `pycharm_workspace` 保持只读，作为事实追溯来源。它不是当前依据——
任何冲突以本仓库的代码、`adr/` 和现役契约为准。
