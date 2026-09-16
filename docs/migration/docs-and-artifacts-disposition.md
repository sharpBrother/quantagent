---
title: 旧仓文档与制品处置标准
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - frozen/
  - docs/adr/
  - docs/research/
  - tests/contracts/
---

# 旧仓文档与制品处置标准

## 两个方向的错误都要避免

把旧仓 `docs/`（3422 个文件）与制品目录整体搬过来，会把已失效的口径、
自相矛盾的结论和过程痕迹一起带进新仓，等于没有重构。

但整体清空同样是错的，因为其中有两类东西仍在起作用：

1. **仍在生效的口径裁定**——它们还约束着当前代码的行为
2. **可复现输入**——它们是现役发布链路的运行前提，且不可重算

因此统一做法是**按内容和用途逐项定性**。

分类依据是**内容还在不在起作用**，不是文件名有没有编号。去编号化是新体系
的命名规则（见 [../adr/2026-09-16-docs-without-numbering.md](../adr/2026-09-16-docs-without-numbering.md)），
不是旧文档的去留标准。

## 五类定性

| 类别 | 判定 | 去向 |
|---|---|---|
| 冻结制品与可复现输入 | 被现役发布或计算链路直接读取 | **迁入 `frozen/`**，连同完整性合同一并迁移；对应裁定正文改写为新体系 ADR |
| 仍在生效的口径裁定 | 仍约束当前代码行为的数据口径、接口或发布边界 | 改写进 `docs/adr/` 或 `docs/domain/`，保留原结论与日期，附旧仓指针 |
| 有效知识 | 方法论、失败教训、数据陷阱、口径踩坑记录 | 提炼进 `docs/research/` 或 `docs/domain/`，**重写而非照搬** |
| 过程记录 | TASK / REVIEW 的流程正文、评审痕迹、编号台账 | 不迁移，旧仓追溯 |
| 已被取代或自相矛盾 | 有更新结论覆盖，或与代码实际行为冲突 | 不迁移，清单里记一行判定与依据 |

### 关于「重写而非照搬」

第三类的处理方式是刻意的。旧文档的写法适配旧的编号体系与流程语境，照搬会
把那套语境一起带进来。提炼的产出应该是"这个陷阱是什么、怎么避免"，而不是
"当时某个任务发现了这个陷阱"。

### 关于第五类的记录

已被取代的文档不迁移，但**要在清单里记一行**判定与依据。理由：旧仓
`docs/decisions/README.md` 不得不维护一张「已知会误导的旧合同」清单，说明
"某份文档不要信"本身是有价值的信息。记一行比让人三个月后重新发现便宜。

## 冻结 bundle：这一节的重点

### 以 bond_timing 为范例

旧仓
[`docs/decisions/2026-09-13-bond-timing-exhibit-freeze-bundle.md`](/Users/le/PycharmProjects/pycharm_workspace/docs/decisions/2026-09-13-bond-timing-exhibit-freeze-bundle.md)
裁定的 `outputs/bond_timing_exhibit_freeze/` 实际内容：

```
outputs/bond_timing_exhibit_freeze/
├── manifest.json                      3.9KB
└── bond_timing/
    ├── config.json
    └── data/
        ├── nav.csv                    1.0MB, 3563 行
        └── signals.csv                667KB, 3564 行
```

它是展厅刷新脚本的**运行前提**而非历史存档——冻结前缀不重算、不覆盖，
增量只从冻结点之后重放。按"产物不入库"一刀切会直接破坏发布能力。

### manifest 的实际字段（迁移时必须保留）

旧 manifest 已经是一份相当完整的完整性合同，新仓的 `frozen/` manifest
结构以它为基础：

| 字段组 | 内容 | 作用 |
|---|---|---|
| 制品身份 | `schema`、`schemaVersion`、`track`、`strategyId`、`decisionCode` | 这是什么制品 |
| 冻结窗口 | `windowStart`、`windowEnd` | 冻结边界在哪，增量从哪之后重放 |
| 配置绑定 | `configPath`、`configSha256`、`configDigest` | 按 bundle 的配置运行，不退回代码默认值 |
| 来源 run | `freezeSource`（`sourceRun`、`generatedAt`、`status`、`inputDigest`、`outputDigest`） | 可追溯到哪次运行产生 |
| 运行状态 | `sourceStatus`（指标、行数、成本参数、起止时间） | 当时的完整上下文 |
| 边界声明 | `researchOnly`、`noDatabaseWrite`、`dmlCount`、`production_qualified` | research-only 边界，不是生产授权 |
| 文件合同 | `files.<name>`：`path`、`sha256`、`rows`、`columns` | 逐文件的 digest 与行列合同 |

`files` 里逐文件带 `columns` 全列表是关键设计——它让"CSV 少了一列"这种
问题在校验时就暴露，而不是在下游计算时以奇怪的方式失败。

### 迁移要求

1. **完整迁移，不做裁剪**。manifest、config、data 全部迁入
   `frozen/bond_timing/exhibit_freeze/`。
2. **digest 必须仍然校验通过**。迁移后跑一次
   `tests/contracts/test_frozen_bundles.py`，`sha256` 与行数、列名全部
   比对。任何不一致说明迁移过程改动了内容。
3. **换行规范必须保持 LF**。`.gitattributes` 已将 `frozen/**` 标为
   `text eol=lf`。这是 digest 稳定的前提——CRLF 会让每个 sha256 都变。
4. **裁定正文改写为新体系 ADR**。原决策文档的结论、日期与理由改写进
   `docs/adr/`，附旧仓指针；不照搬原文的编号与流程语境。
5. **体积例外要显式**。`nav.csv` 有 1MB，超过一般文件的 512KB 上限。因此
   `frozen/` 的单文件上限单独设为 4MB，pre-commit 与 CI 都做了对应处理。
   这是显式例外，不是开后门——超过 4MB 仍需单独评估。

### frozen/ 的目录与约束

见 [../../frozen/README.md](../../frozen/README.md)。要点：只读、逐 bundle
带 manifest、digest 按 LF 计算、配置不得退回代码默认值、契约测试强制校验、
体积克制。

`frozen/` 与 `publish/` 的区别是方向：**`publish/` 是产出，`frozen/` 是
输入**。混在一起会让人以为 `frozen/` 也可以重新生成，而且 `publish/` 由
装配器覆写，会把输入冲掉。

设计依据见 [../adr/2026-09-16-frozen-artifacts.md](../adr/2026-09-16-frozen-artifacts.md)。

## outputs/ 与 reports/ 需要逐项过一遍

这两个目录**不能按目录一刀切**：

| 内容 | 处置 |
|---|---|
| 可重算的展示产物（图表、汇总表） | 不迁。新链路重新生成 |
| 发布必需的不可重算输入（如上述 bundle） | 必迁 `frozen/` |
| 一次性的调试输出 | 不迁 |
| 有价值但已失去上游的历史结果 | 判定是否冻结；若无现役消费者则不迁，只在清单记一行 |

旧仓 `reports/` 有 1.3G，`.gitignore` 里有 110 条 `reports/` 的逐任务例外。
这批例外本身就是"按目录一刀切不可行"的证据——每次都要为某个具体产物开
例外，说明目录级规则和实际需求不匹配。

新规则以**内容性质**为准：能重算的不入库，不能重算且发布必需的入
`frozen/`，发布产物入 `publish/`，其余一律 `var/`。

## 清单的生成方式

不靠人工回忆，靠反查：

1. **反查现役读取**：grep 现役模块对 `outputs/`、`reports/`、
   `data_registry/` 的路径引用，得到"哪些制品有现役消费者"。
2. **反查文档引用**：grep 现役文档对旧文档的引用，得到"哪些旧文档仍被
   指向"。
3. **反查代码行为**：对声称约束代码行为的口径裁定，检查代码是否真的按它
   执行。不一致的归入第五类（自相矛盾）。
4. **剩余的默认归入第四或第五类**，但每一项都要有一行判定依据。

清单以本文档的表格形式逐项记录，是 P5 的交付物。冻结制品的迁移在 P5，
但**清单本身要在 P2 完成**——因为它决定了哪些东西不能在清理旧仓时被删掉。

## 与代码模块清点的分工

代码模块的处置见
[../architecture/legacy-inventory.md](../architecture/legacy-inventory.md)；
数据表见 [wx2-disposition.md](wx2-disposition.md)。三份清单的分类标准不同，
不要互相套用——代码看"逻辑是否还要用"，数据表看"能否重算"，文档制品看
"内容是否还在起作用"。
