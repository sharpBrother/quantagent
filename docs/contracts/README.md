---
title: 数据契约体系
status: active
created: 2026-09-16
updated: 2026-09-18
applies_to:
  - src/quantagent/contracts/
  - tests/contracts/
---

# 数据契约体系

## 为什么契约必须是代码

旧仓 `docs/data_dictionary/` 有 318 张表的字典，是 markdown。它无法回答一个
关键问题：**这份字典和实际的表结构一致吗？**

文档式字典的失效是必然的，因为改表结构不需要改文档，而不改文档也不会有
任何后果。契约是代码，它在 CI 中运行，不一致就失败。

## 契约的三种形态

| 形态 | 工具 | 位置 | 描述什么 |
|---|---|---|---|
| DataFrame schema | pandera | `contracts/schemas/{pg,ops,lake}/` | 列名、类型、约束、键、空值策略 |
| JSON schema | pydantic | `contracts/schemas/publish/` | 发布产物结构 |
| 可见性规则 | YAML | `contracts/visibility/` | 时间形态与 PIT 规则 |

三者合起来描述一个数据集的完整语义：**它长什么样**（schema）、**它什么时候
能被知道**（visibility）、**它的键是什么**（temporal_kind 与键定义）。

## 每个数据集必须有什么

1. 一份 schema（列、类型、键、约束）
2. 一份 visibility 规则（`temporal_kind`、可见性规则、`grade`、`rationale`）
3. 一条 `reads` 声明（如果它有上游）

三者缺一即 CI 失败。visibility 规则缺失是硬阻断——见
[../domain/pit-rules.md](../domain/pit-rules.md)。

## 契约与文档的双向绑定

这是本体系的关键机制，解决"文档和实现哪个是真的"这个问题。

### 从文档到契约：applies_to

每份 `docs/` 文档的 frontmatter 有 `applies_to`，列出它约束哪些代码路径。
改动落在某份文档的 `applies_to` 范围内，就必须确认该文档仍然成立。

### 从契约到文档：doc_ref

每份 schema 与 visibility 规则带 `doc_ref` 字段，指向解释它的文档：

```yaml
dataset: mart.fin_statement
doc_ref: docs/domain/temporal-semantics.md#period_with_revision
temporal_kind: period_with_revision
# ...
```

### 双向校验

`tests/contracts/test_docs_contract_binding.py` 校验两件事：

1. 每份文档的 `applies_to` 路径都存在
2. 每个契约的 `doc_ref` 指向的文档与锚点都存在

单向绑定不够：只有 `applies_to` 时，新增契约可能没有任何文档解释；只有
`doc_ref` 时，文档可能约束了已删除的代码。

### 分工原则

**契约是权威，文档是解释。**

契约说明"是什么"（列名、类型、规则类型、等级），文档说明"为什么"（为什么
是这个等级、为什么这样分区、这个口径的历史来源）。

两者冲突时以契约为准，然后修文档——因为契约是可执行的，它和实现的一致性
有机器保证。

## 契约变更流程

变更的重量取决于影响范围。

### 加列（向后兼容）

1. 改 schema
2. 跑 `quantagent check contracts`
3. 提交

不需要 ADR。

### 改列类型、改键、改约束

1. 评估影响：哪些下游数据集与因子会受影响
2. 改 schema，同步改受影响的 `reads` 声明
3. 受影响的物化资产重跑
4. 若涉及口径变化，`docs/adr/` 记一份

### 改可见性规则

最重的一类，因为它会改变所有历史 `knowledge_dt`。首次从旧仓下游取数反推
写入 YAML 不算变更；改已有规则才走下面四步。

1. **变更前跑影响评估**：多少数据集、多少因子、多少已发布结论的
   `knowledge_dt` 会变
2. `docs/adr/` 记一份，说明原因与影响范围
3. 受影响的因子**必须重算**，不允许新旧规则的结果混存
4. 已发布结论若受影响，在产物里标注"因规则修订而重算"

第三条是硬要求：同一份因子长表里混着两种规则算出的 `knowledge_dt`，会让
任何 PIT 查询结果无法解释。

### 删数据集

1. 确认零消费者（代码反查 + 血缘图）
2. 契约与 schema 一并删除
3. 数据本身按"可重算/不可重算"处置：可重算的直接删，不可重算的按
   [../migration/docs-and-artifacts-disposition.md](../migration/docs-and-artifacts-disposition.md)
   的标准判定是否冻结

## 契约校验在哪里跑

| 时机 | 校验内容 |
|---|---|
| pre-commit | YAML / TOML / JSON 语法 |
| CI | schema 自洽、visibility 规则完整性、双向绑定、文档 frontmatter、冻结制品 digest |
| 物化时 | 写入前按 schema 校验 DataFrame，不通过不落盘 |
| 适配器出口 | 读取结果按 schema 校验，防止三套适配器行为分叉 |

写入时校验是最重要的一环——它保证落盘的数据一定符合契约，下游可以无条件
信任。旧仓缺的正是这一环：`to_sql(append)` 无约束写入，脏数据进库后才被
发现。

## 命名与组织

```
src/quantagent/contracts/
├── schemas/
│   ├── pg/          源原生表（按源分文件）
│   ├── ops/         控制状态表
│   ├── lake/        std / mart / feature / model / signal / portfolio
│   └── publish/     发布产物
└── visibility/      一个数据集一个 YAML，文件名与 dataset 对应
```

文件名与数据集名一致，便于从数据集名直接定位契约。不使用编号。
