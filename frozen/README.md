---
title: frozen 冻结输入制品
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - frozen/
  - src/quantagent/publish/
---

# frozen：冻结输入制品

这里存放**被现役计算或发布链路直接读取的、不可重算的输入**。它与
`publish/` 的区别是方向：`publish/` 是产出，`frozen/` 是输入。

## 为什么需要这个目录

旧仓的 `outputs/bond_timing_exhibit_freeze/` 是展厅刷新脚本的运行前提——
冻结前缀不重算、不覆盖，增量只从冻结点之后重放。这类东西既不是文档，也
不是可重算的中间结果，如果按「产物一律不入库」处理就会丢掉发布能力。

## 硬约束

1. **只读**。冻结 bundle 一经提交不得修改。需要变更时新建 bundle 并在
   `docs/adr/` 记录取代关系。
2. **逐 bundle 带 `manifest.json`**，内容至少包括：制品身份、来源 run 身份、
   冻结窗口、配置摘要、每个文件的 digest、行数与列合同、以及
   research-only / no-write 边界声明。
3. **digest 按统一 LF 计算**。`.gitattributes` 已将 `frozen/**` 标为
   `text eol=lf`，避免 Windows checkout 的 CRLF 造成校验失败。
4. **配置不得退回代码默认值**。bundle 内显式记录运行配置，读取方按 bundle
   的配置运行，不允许因字段缺失而回退到代码里的默认参数。
5. **契约测试强制校验**。`tests/contracts/test_frozen_bundles.py` 校验每个
   bundle 的 manifest 完整性、digest 一致性与行列合同，防止被静默改写。
6. **体积克制**。这里入 git，因此只放发布必需的最小输入。可重算的东西一律
   不进来——旧仓 `.git` 涨到 573M 就是因为没守住这条。单文件上限 4MB（其余
   目录是 512KB），因为冻结制品的体积由制品本身决定，不可压缩；超过 4MB
   需要单独评估，不自动放行。

## 目录约定

```
frozen/<research_line>/<bundle_name>/
├── manifest.json
├── config.json          # 显式运行配置
└── data/                # nav.csv / signals.csv 等
```

迁移判定标准见 [docs/migration/docs-and-artifacts-disposition.md](../docs/migration/docs-and-artifacts-disposition.md)。
