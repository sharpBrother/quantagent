---
title: publish 层职责
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/publish/
  - publish/
  - frozen/
---

# publish：发布产物装配

## 负责

- **装配**：把任意上游层的结果组装为 `publish/*.json`。
- **校验**：按 `contracts/schemas/publish/` 校验后才写盘。
- **读取冻结输入**：从 `frozen/` 读取不可重算的发布前提，校验 digest 与
  行列合同后使用。
- **PIT 报告装配**：汇总各输入的 PIT 等级、`pit_from`、不可信区间样本占比，
  写入产物的 `pit_report` 字段。

## 不负责

| 排除项 | 正确归属 |
|---|---|
| 任何业务计算 | 上游各层 |
| 前端渲染 | `apps/web` |
| 重算冻结前缀 | 不允许。冻结即冻结 |

**装配器里不允许出现业务计算。** 如果发现需要在装配时算点什么，说明上游缺
了一个资产。

## 允许依赖

任意上游数据层。这是刻意的：宏观指标可以从 `std` / `mart` 直达发布，因子
评价可以从 `feature` 直达发布，不需要绕路制造中间层。

## 硬约束

- **每个产物携带 `pit_report`**，发布层强制展示，不得隐藏。低 PIT 等级的
  数据允许发布，但可信度信息必须一同呈现——这是声明式管控的最后一环。
- **每个产物携带运行身份**：`run_id`、代码版本、数据截止日、配置 digest。
  不能追溯身份的结果不发布。
- **`frozen/` 只读**。冻结前缀不重算、不覆盖，增量只从冻结点之后重放。
  读取前必须校验 digest；校验失败即停止，不降级运行。
- **配置不得退回代码默认值**。冻结 bundle 内显式记录运行配置，按 bundle
  的配置运行；字段缺失时报错，不回退到代码默认参数。
- **不手工维护产物**。`publish/` 的内容一律由装配器生成。
- **前端只读**。`apps/web` 不直连数据库，不读 `var/`，不反向写入。

## 典型反例

- **大文件入库**。`publish/` 只放小体积 JSON。旧仓 `data_registry/` 389M
  全量入库、`outputs/` 43M，且有 21MB 的 `positions.csv` 被跟踪。
- **手工编辑发布 JSON**。改内容要改上游数据或装配逻辑。手改一次，下次
  重跑就丢。
- **把冻结制品当可重算产物清理掉**。旧仓 `outputs/bond_timing_exhibit_freeze/`
  是展厅刷新的运行前提，按目录一刀切会直接破坏发布能力。判定标准见
  [../../migration/docs-and-artifacts-disposition.md](../../migration/docs-and-artifacts-disposition.md)。
- **多个装配入口**。发布产物的最终装配只能有一个权威入口，否则同名产物会
  被不同脚本以不同口径覆盖。
- **只展示数值、隐藏 PIT 等级**。这会让「声明式而非硬阻断」的设计失效——
  不阻断的前提是信息透明。

## 对应的机械检查

- import-linter `只有 ingest 与 adapters 可以接触 PostgreSQL 驱动`。
- `tests/contracts/test_frozen_bundles.py`：每个 bundle 的 manifest 完整性、
  digest 一致性、行列合同。
- `tests/contracts/`：发布产物 schema 校验，含 `pit_report` 与身份字段的
  必填性。
- CI 超大文件拦截（>512KB）。
