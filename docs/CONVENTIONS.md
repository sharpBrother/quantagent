---
title: 文档公约
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - docs/
  - tests/contracts/test_docs_frontmatter.py
---

# 文档公约

## 为什么需要这一份

旧仓 `docs/` 有 3422 个文件，其中 2564 份带编号（TASK 733、REVIEW 1270、
AR 250、AC 195、ADR 77、DESIGN 34），而只有 7% 的 markdown 带状态字段。
结果是：无法判断一份文档是否还生效，`docs/decisions/README.md` 不得不专门
维护一张「已知会误导的旧合同」清单。

根因不是文档太多，是**文档没有生命周期**。本公约解决这一点。

## 四类文档，各有生命周期

| 目录 | 类别 | 生命周期 | 判断标准 |
|---|---|---|---|
| `architecture/` | 活文档 | 代码变则同步改，永远描述**当前**状态 | 读者按它理解现在的系统 |
| `adr/` | 决策记录 | 日期命名，只增不改，被取代时标 `superseded_by` | 读者按它理解**当初为什么这么选** |
| `contracts/`、`domain/` | 口径与契约 | 与可执行 schema 双向绑定，同步演进 | 读者按它理解数据含义 |
| `runbook/`、`research/` | 操作手册与研究笔记 | 按需更新，过期即归档 | 读者按它执行操作或复用结论 |

`migration/` 是一次性目录，P6 完成后整体转入 `adr/` 的历史记录，不长期维护。

区分 `architecture/` 与 `adr/` 是这套体系的关键：**活文档被改写，决策记录
不被改写**。旧仓的混乱很大程度源于把两者混在同一批编号文档里，于是既不敢
改（怕丢历史），也不敢信（怕已过期）。

## 强制 frontmatter

每份 markdown 必须以 YAML frontmatter 开头：

```yaml
---
title: 简短标题
status: active          # active | superseded | archived
created: 2026-09-16
updated: 2026-09-16
applies_to:             # 这份文档约束哪些代码路径
  - src/quantagent/domain/pit/
supersedes: null        # 取代了哪份文档（相对 docs/ 的路径）
superseded_by: null     # 被哪份文档取代
---
```

`applies_to` 是硬性要求，它让「改了代码要不要改文档」有客观依据：改动落在
某份文档的 `applies_to` 范围内，就必须确认该文档仍然成立。

`tests/contracts/test_docs_frontmatter.py` 在 CI 中校验：字段齐全、`status`
取值合法、`superseded_by` 指向的文件存在、`applies_to` 的路径存在。

## 不使用编号

不设文档编号，不设编号台账，不设编号 allocator。文件名用 `kebab-case` 描述
内容，ADR 额外前置日期：`adr/2026-09-16-storage-selection.md`。

理由：编号的唯一作用是稳定引用，但文件路径已经能稳定引用；而编号带来的
成本是真实的——旧仓的 `DOC_NUMBER_RESERVATIONS.json` 有 9236 行、745 条
记录，纯粹是台账维护开销。

**但去编号不等于按命名删文档。** 旧仓文档的去留按内容定性，见
[docs-and-artifacts-disposition.md](migration/docs-and-artifacts-disposition.md)。

## 默认不写文档

日常任务直接写代码和测试。只有这四种情况才在 `docs/` 留一份：

1. 改变了数据口径、目标表、公共接口或外部副作用；
2. 做了一个后来的自己会想问「当初为什么这么选」的技术取舍；
3. 项目负责人给出了需要长期生效的口径裁定；
4. 新增或改变了一个数据集的可见性规则、时间形态或 PIT 等级。

不需要：PRD、Gate 流程、评审文档、任务验收报告、编号预留。

## 取代而不删除

一份 `adr/` 被新决策取代时：新文档写 `supersedes`，旧文档改 `status:
superseded` 并写 `superseded_by`，**正文不改写**。这样历史推理链保持完整，
同时读者能立刻知道它不再是当前依据。

`architecture/` 活文档相反——直接改写，因为它的职责就是描述当前状态。需要
知道它为什么变成这样，去看对应的 ADR。

## notebooks 的过期规则

`notebooks/` 是探索性代码的唯一去处。超过 6 个月未修改且结论未被任何文档
引用的 notebook 直接删除；有价值的结论在删除前提炼进 `docs/research/`。
notebook 是草稿，不是知识载体。详见 [notebooks/README.md](../notebooks/README.md)。

## 冲突处理

发现文档结论与代码实际行为矛盾时：**以代码为准记录事实，然后停下来问**，
不要自行判断哪个对。这类矛盾往往意味着某次改动漏了口径同步，需要确认的是
「哪个是本意」而不是「哪个是现状」。
