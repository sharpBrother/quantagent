---
title: publish 发布产物
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - publish/
  - src/quantagent/publish/
  - apps/web/
---

# publish：发布产物

`apps/web` 消费的 JSON 产物，由 `quantagent publish build` 生成，按
`src/quantagent/contracts/schemas/publish/` 校验后写入。

## 约束

1. **只放小体积 JSON**。大表、明细、CSV 不进这里。旧仓 `data_registry/`
   389M 全量入库是要避免的反面案例。
2. **每个产物携带 `pit_report`**：各输入的 PIT 等级、`pit_from`、回测区间
   中落在不可信区间的样本占比。发布层强制展示，不得隐藏。
3. **每个产物携带运行身份**：`run_id`、代码版本、数据截止日、配置 digest。
   不能追溯身份的结果不发布。
4. **前端只读**。`apps/web` 不直连任何数据库，也不反向写入这里。
5. **不手工维护**。这里的内容一律由装配器生成；需要改内容就改上游数据或
   装配逻辑，不直接编辑 JSON。
