---
title: 测试组织约定
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - tests/
---

# 测试组织约定

旧仓 427 个测试文件全部平铺在一个目录里，且有 24 个是 `test_task0441_*` 这
类一次性验收测试。新仓按**测试的作用**分四类，目录结构镜像 `src/quantagent/`。

| 目录 | 作用 | 可用外部依赖 |
|---|---|---|
| `unit/` | 单个模块的行为。`domain/` 的规则测试全部落在这里，且必须在零数据库、零文件的条件下通过 | 无 |
| `contracts/` | 端口行为契约。同一套测试跑在 `adapters.postgres`、`adapters.lake`、`adapters.memory` 三套实现上，三者行为必须一致 | 由 fixture 提供 |
| `golden/` | 与旧仓口径对拍。用旧库真实数据 snapshot 做 fixture，固化旧实现的既有行为，新实现必须跑通同一套，差异必须有解释 | fixture 快照 |
| `integration/` | 跨层链路。物化、编排、发布产物装配 | 本地 PG / Parquet |

## 命名

按被测对象命名，不按任务编号命名。`test_calendar_trading_days.py` 而不是
`test_task0441_coverage_frame_scope.py`——任务编号在三个月后没有任何检索
价值，而且会让人误以为测试是一次性的。

## golden 测试的作用边界

`golden/` 的目的是**防止重构顺手改了口径**，不是证明旧实现正确。如果对拍
发现差异且判定旧实现有错，处理方式是：修正新实现的期望值、在 `docs/adr/`
记一页说明差异原因，然后更新 golden 基线。不允许静默改基线。

## 文档与契约的校验也是测试

`contracts/test_docs_frontmatter.py` 校验 `docs/` 下所有文档的 frontmatter
完整性，`contracts/test_frozen_bundles.py` 校验 `frozen/` 下每个 bundle 的
digest 与行列合同。这两项在 CI 中与代码测试同等对待。
