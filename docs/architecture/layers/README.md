---
title: 分层职责定义索引
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/
  - orchestration/
  - pyproject.toml
---

# 分层职责定义

## 为什么要有这一组文档

`import-linter` 能证明「没有反向 import」，不能证明「这段逻辑放对了层」。
`ruff` 和 `mypy` 同理——它们检查形式，不检查归属。

旧仓的分层混乱正是形式检查抓不到的那一类：139 个文件直接 `import
dbconnect` 绕过 Gateway，每一处单独看都合法，合起来就是「读边界形同虚设」。
417 个文件靠 `sys.path.insert` 运行，每一处都能跑，合起来就是「这个项目不是
一个包」。

所以职责必须写下来，且必须写明**不负责什么**和**典型反例**——只写「负责
什么」的文档无法用来驳回一个放错位置的实现。

## 三层防护，各管一段

| 手段 | 管什么 | 管不了什么 |
|---|---|---|
| 本组文档 | 职责归属、典型反例 | 无法自动执行 |
| 契约测试（`tests/contracts/`） | 行为口径一致性 | 无法覆盖未写测试的行为 |
| import-linter / ruff / mypy | 依赖方向、循环、风格、类型 | 无法判断逻辑该放哪层 |

新增模块前先读对应层的这份文档。发现某个实现的归属存在争议，先在文档里
补一条反例，再改代码。

## 每份文档的固定结构

1. **负责** — 这一层的职责清单
2. **不负责** — 明确排除的职责，以及它们的正确归属
3. **允许依赖** — 可以 import 哪些层
4. **典型反例** — 具体的错误做法，多数来自旧仓的真实情况
5. **对应的机械检查** — 哪条 import-linter 契约或测试覆盖了这一层

## 索引

| 层 | 一句话职责 |
|---|---|
| [platform.md](platform.md) | 技术基础设施，唯一接触连接串的地方 |
| [contracts.md](contracts.md) | 可执行契约：schema 与可见性规则 |
| [domain.md](domain.md) | 口径规则，零存储依赖 |
| [adapters.md](adapters.md) | 存储适配器，实现 `domain.ports` |
| [ingest.md](ingest.md) | 外部源到 PG 研究数据面，唯一写 PG 的层 |
| [lake.md](lake.md) | Parquet 物化与读取 |
| [features.md](features.md) | 因子与特征面板 |
| [models.md](models.md) | 建模抽象，线性与 ML 共用 |
| [strategy.md](strategy.md) | 信号生成与回测 |
| [portfolio.md](portfolio.md) | 组合构建、风险、归因 |
| [agents.md](agents.md) | 研究 Agent 与观点组织 |
| [publish.md](publish.md) | 发布产物装配 |
| [cli.md](cli.md) | 统一命令行入口，composition root |
| [orchestration.md](orchestration.md) | Dagster 资产化编排，composition root |
