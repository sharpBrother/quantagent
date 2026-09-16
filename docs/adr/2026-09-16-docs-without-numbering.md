---
title: 文档体系去编号化
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - docs/
  - tests/contracts/test_docs_frontmatter.py
supersedes: null
superseded_by: null
---

# 文档体系去编号化

## 背景

旧仓 `docs/` 的状况：

- 3422 个文件，其中 2564 份带编号体系：TASK 733 份、REVIEW 1270 份、
  AR 250 份、AC 195 份、ADR 77 份、DESIGN 34 份
- 编号台账 `DOC_NUMBER_RESERVATIONS.json` 有 9236 行、745 条预留记录
- 只有约 7% 的 markdown 带状态字段
- 四个并行入口：`docs/README.md`、`docs/STATUS.md`、
  `docs/decisions/README.md`、`docs/legacy/README.md`
- `docs/decisions/README.md` 不得不专门维护一张「已知会误导的旧合同」清单

最后一条是关键信号：文档体系已经需要一份"哪些文档不要信"的元文档。

根因不是文档太多。根因是**文档没有生命周期**——无法判断一份文档是否还
生效，于是既不敢删（怕丢历史），也不敢信（怕已过期），只能不断新增。

## 决策

### 不使用任何编号体系

不设文档编号，不设编号台账，不设编号 allocator。文件名用 `kebab-case`
描述内容；ADR 额外前置日期（`2026-09-16-storage-selection.md`）。

### 四类文档，各有明确生命周期

| 目录 | 类别 | 生命周期 |
|---|---|---|
| `architecture/` | 活文档 | 代码变则同步改，永远描述当前状态 |
| `adr/` | 决策记录 | 只增不改，被取代时标 `superseded_by` |
| `contracts/`、`domain/` | 口径与契约 | 与可执行 schema 双向绑定 |
| `runbook/`、`research/` | 操作手册与研究笔记 | 按需更新，过期即归档 |

### 强制 frontmatter

`title` / `status` / `created` / `updated` / `applies_to` / `supersedes` /
`superseded_by`。由 `tests/contracts/test_docs_frontmatter.py` 在 CI 校验。

### 唯一入口

`docs/README.md` 是唯一的文档导航。

完整公约见 [../CONVENTIONS.md](../CONVENTIONS.md)。

## 理由

1. **编号的唯一作用是稳定引用，而文件路径已经能稳定引用**。git 也能追溯
   重命名。
2. **编号的成本是真实的**：台账维护、预留冲突、分配流程，9236 行的
   `DOC_NUMBER_RESERVATIONS.json` 是纯开销。
3. **编号无法解决真正的问题**。旧仓有完整的编号体系，但仍然无法判断一份
   文档是否生效——因为那取决于 `status` 和 `applies_to`，不取决于编号。
4. **区分活文档与决策记录是关键**。旧仓的混乱很大程度源于把两者混在同一批
   编号文档里：活文档不敢改（怕丢历史），决策记录被改写（丢了推理链）。
   分开后，活文档放心改写，决策记录放心保留。
5. **`applies_to` 让"改代码要不要改文档"有客观依据**。改动落在某份文档的
   `applies_to` 范围内，就必须确认它仍然成立。这比"记得同步文档"可靠。
6. **CI 校验让 frontmatter 不会退化**。旧仓 7% 的状态字段覆盖率说明"约定"
   不足以维持一致性。

## 被否方案

| 方案 | 否决理由 |
|---|---|
| 保留编号体系但加状态字段 | 编号成本仍在，而它解决不了任何问题 |
| 只保留 ADR 编号（ADR-001 那种） | 日期前缀已提供排序与唯一性，编号多余 |
| 用 issue 编号替代文档编号 | 引入对外部系统的依赖；离线不可读 |
| 不做 frontmatter 强制，靠约定 | 旧仓 7% 的覆盖率已经证明约定不够 |
| 保留多个入口文档 | 读者不知道从哪开始，这是旧仓的实际问题 |

## 代价

1. **文件重命名会断链**。跨文档引用用相对路径，重命名需要一并改。CI 的
   `applies_to` 校验能发现部分断链，但文档间的 markdown 链接需要额外检查。
2. **没有编号意味着口头引用不便**。"你看一下那个 TASK 0441"比"你看一下
   docs/domain/pit-rules.md"短。但后者更明确。
3. **frontmatter 是每份文档的固定开销**。七个字段，写起来有摩擦。这是刻意
   的——它让"随手写一份文档"有一点成本，配合"默认不写文档"的原则。
4. **`applies_to` 需要维护**。代码路径重构后要同步改。

## 推论

1. **去编号不等于按命名删文档**。旧仓文档的去留按**内容**定性，见
   [../migration/docs-and-artifacts-disposition.md](../migration/docs-and-artifacts-disposition.md)。
   有编号的文档里有仍在生效的口径裁定，必须迁移。
2. **过程记录不迁移**。TASK / REVIEW 的流程正文、评审痕迹、编号台账留在
   旧仓追溯。它们的内容是"当时怎么推进的"，不是"现在该怎么做"。
3. **默认不写文档**。只有四种情况才留一份：改了数据口径或公共接口、做了
   需要解释的技术取舍、有需要长期生效的口径裁定、新增或改变了数据集的
   可见性规则。
4. **不需要 PRD、Gate 流程、评审文档、任务验收报告、编号预留**。
5. **notebooks 有独立的过期规则**，见 `notebooks/README.md`。
