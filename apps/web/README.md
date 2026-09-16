---
title: apps/web 展示层占位
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - apps/web/
  - publish/
---

# apps/web：展示层（占位）

Next.js 应用，从旧仓 `website/` 迁移，属于 P5 阶段。当前是占位目录。

## 边界

1. **只读 `publish/*.json`**，带 schema 校验的 loader。不直连任何数据库，
   不读 `var/`，不反向写入任何数据层。
2. **独立工具链**。Node / TypeScript / Next.js 版本以本目录的
   `package.json` 为准，与 Python 侧的 3.12 基线无关。
3. **产物不入库**：`node_modules/`、`.next/`、构建缓存均已 gitignore。
4. **必须展示 PIT 等级**。含 `pit_report` 的产物在页面上不得只展示数值而
   隐藏可信度——这是 PIT 声明式管控的最后一环。

## 迁移要点

旧仓 `website/` 有 132 个 ts/tsx/js/css 文件、约 2 万行，以及 Playwright
e2e 与若干 schema 校验脚本。迁移时保留 loader 的 schema 校验和 e2e，页面
按当前发布产物重新对齐，不照搬已停用的页面。
