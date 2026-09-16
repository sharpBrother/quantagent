---
title: notebooks 探索性分析
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - notebooks/
---

# notebooks：探索性分析的唯一去处

本仓库没有 `scripts/` 目录。一次性的探索、验算、数据摸底都放在这里，而不是
在根目录或 `scripts/` 里堆 `.py`。

## 约定

1. **jupytext 配对**：只提交 `.py`（percent 格式），不提交 `.ipynb`。
   `.gitignore` 已忽略 `*.ipynb`。这样 notebook 可以 diff、可以 review。
2. **命名带日期与主题**：`2026-09-16-etf-turnover-decay.py`。日期是为了让
   过期判定有依据。
3. **过期清理**：超过 6 个月未修改且结论未被任何文档引用的 notebook 直接
   删除。有价值的结论应当在删除前提炼进 `docs/research/`——notebook 本身
   不是知识载体，它是草稿。
4. **不被依赖**：`src/` 与 `orchestration/` 下的代码不得 import notebook。
   探索出来的东西要复用就搬进 `src/`，并补测试。
5. **不写库**：notebook 里不允许出现数据库写入。需要写库就做成 CLI 子命令
   或 Dagster asset，走 `AGENTS.md` 的写入保护。
