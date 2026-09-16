---
title: 不可重算历史制品的冻结策略
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - frozen/
  - src/quantagent/publish/
  - tests/contracts/
  - .gitattributes
supersedes: null
superseded_by: null
---

# 不可重算历史制品的冻结策略

## 背景

初版的仓库瘦身方案是「`var/` 整体 gitignore，产物一律不入库」。这条规则
解决了旧仓的体积问题（工作树 4.5G、`.git` 573M、`data_registry/` 389M 全量
入库、115 个 >1MB 文件被跟踪），但它会破坏发布能力。

具体的反例是旧仓的
[`docs/decisions/2026-09-13-bond-timing-exhibit-freeze-bundle.md`](/Users/le/PycharmProjects/pycharm_workspace/docs/decisions/2026-09-13-bond-timing-exhibit-freeze-bundle.md)
所裁定的 `outputs/bond_timing_exhibit_freeze/`。它包含 `manifest.json`、
`bond_timing/config.json` 以及 `data/nav.csv`、`data/signals.csv`，是展厅
刷新脚本的**运行前提**而非历史存档——冻结前缀不重算、不覆盖，增量只从
冻结点之后重放。

如果按"产物不入库"一刀切，这个 bundle 会被清掉，展厅刷新直接失效。

同类情形还有一批：依赖已失效外部输入或已丢失中间状态的历史结果，它们既不
能重算，又是现役链路的输入。

## 决策

新增 `frozen/` 目录，git 跟踪，专门存放**不可重算且被现役链路直接读取的
输入制品**。

方向上与 `publish/` 相反：

| 目录 | 方向 | 内容 |
|---|---|---|
| `frozen/` | 输入 | 不可重算的发布前提 |
| `publish/` | 产出 | 发布 JSON |
| `var/` | 中间 | 可重算，gitignore |

### 约束

1. **只读**。一经提交不得修改。需要变更时新建 bundle，在 ADR 记录取代关系。
2. **逐 bundle 带 `manifest.json`**：制品身份、来源 run 身份、冻结窗口、
   配置摘要、每个文件的 digest、行数与列合同、research-only / no-write
   边界声明。
3. **digest 按统一 LF 计算**。`.gitattributes` 已将 `frozen/**` 标为
   `text eol=lf`，避免 Windows checkout 的 CRLF 造成校验失败。
4. **配置不得退回代码默认值**。bundle 内显式记录运行配置，读取方按 bundle
   的配置运行；字段缺失时报错，不回退到代码默认参数。
5. **契约测试强制校验**。`tests/contracts/test_frozen_bundles.py` 校验
   manifest 完整性、digest 一致性、行列合同。
6. **体积克制**。只放发布必需的最小输入。

### 目录约定

```
frozen/<research_line>/<bundle_name>/
├── manifest.json
├── config.json
└── data/
```

## 理由

1. **发布能力依赖它**。这不是"保留历史存档"的偏好问题，是链路能不能跑的
   问题。
2. **必须随代码一起分发**。放 `var/` 意味着换机器、重装环境后丢失，而它
   不可重算——丢了就永久丢了。
3. **入 git 才能保证不被静默改写**。digest 校验加版本控制，任何改动都留痕。
4. **与 `publish/` 分开命名**，让"输入"和"产出"在目录结构上可见。混在一起
   会让人以为 `frozen/` 也是可重新生成的。
5. **规则简单可执行**。"能重算的不入库，不能重算且发布必需的入 `frozen/`，
   发布产物入 `publish/`，其余一律 `var/`"——这四句话让 `.gitignore` 从
   旧仓的 320 行压到十几行。

## 被否方案

| 方案 | 否决理由 |
|---|---|
| 产物一律不入库 | 破坏发布能力。冻结 bundle 不可重算 |
| 放 `publish/` 里 | 混淆输入与产出；且 `publish/` 由装配器覆写，会把输入冲掉 |
| 放 `var/` 并手工备份 | 换机器即丢失，且没有 digest 保证 |
| 外部对象存储（S3 那类） | 单人项目多一个依赖；且失去随代码版本化的好处 |
| git-lfs | bundle 体积不大（CSV 级别），LFS 增加克隆与 CI 复杂度 |
| 在 `.gitignore` 里为每个 bundle 开例外 | 这正是旧仓 320 行 `.gitignore` 的成因 |

## 代价

1. **仓库会随 bundle 增长**。因此有"体积克制"约束与 CI 的 512KB 单文件
   上限。超过上限的 bundle 需要单独讨论，不自动放行。
2. **判定需要人工**。"能不能重算"没有机械判据，要逐个看。判定标准见
   [../migration/docs-and-artifacts-disposition.md](../migration/docs-and-artifacts-disposition.md)。
3. **只读约束靠纪律加测试**。git 不能真正阻止修改，靠 digest 校验发现。
4. **bundle 累积后需要定期审查**。某个 bundle 的消费者停用后它就该归档，
   但这不会自动发生。

## 推论

1. **`outputs/` 与 `reports/` 需要逐项过一遍**，不能按目录一刀切。其中既有
   可重算的展示产物（不迁），也有像 bond_timing 这样的发布必需输入（必迁）。
2. **换行规范进 `.gitattributes`**。这条继承自旧仓 bundle 裁定中的
   `newline: LF` 约定，是 digest 稳定的前提。
3. **冻结前缀不重算的语义要在读取方实现**。增量只从冻结点之后重放，读取方
   必须知道冻结边界在哪，这个信息在 manifest 里。
4. **digest 校验失败即停止，不降级运行**。降级运行会让"用了被改写的冻结
   数据"变成静默错误。
