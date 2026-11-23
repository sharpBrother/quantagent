---
title: 货币供应 ED_MoneySupply 可见日：InfoPublDate 优先，空则期末次月 15 日
status: active
created: 2026-11-23
updated: 2026-11-23
applies_to:
  - src/quantagent/contracts/visibility/
  - docs/domain/pit-rules.md
supersedes: null
superseded_by: null
---
# 货币供应 ED_MoneySupply 可见日：InfoPublDate 优先，空则期末次月 15 日

## 背景

旧仓 `macro_regime/pit.py` 对 `ED_MoneySupply` 不用 `InfoPublDate`，统一取 `EndDate`
次月 15 日，理由是历史行的 `InfoPublDate` 是批量回补日。`docs/domain/pit-rules.md`
照此登记为 `fixed_lag`、等级 B。

## 决策（负责人 2026-11-23 裁定）

- `InfoPublDate` 非空：可见日 = `InfoPublDate` 的日期，等级 A。
- `InfoPublDate` 为空：可见日 = `EndDate` 次月 15 日，等级 B。

契约写法（`EndDate` 都是月末，月末加 15 个自然日正好是次月 15 日）：

```yaml
visibility:
  rule: source_field
  field: InfoPublDate
  grade: A
  fallback:
    rule: fixed_lag
    field: EndDate
    lag_n: 15
    lag_unit: calendar_day
    grade: B
```

读取前要校验 `EndDate` 都是月末，不是月末就报错。

## 依据与后果（wx2 2026-11-23，660 行）

- 199 行 `InfoPublDate` 为空，走次月 15 日。
- 2024 年以来 30 行的 `InfoPublDate` 早于次月 15 日（实际发布在 12 日到 14 日），可见日比旧仓提前。
- 382 行 `InfoPublDate` 比次月 15 日晚 30 天以上，都是回补日，集中在 2019-05-17
  （267 行）和 2015-01-05（26 行）。2000–2018 年的月度数据全在这一类。
  按本规则，这些月份要到回补日才可见，比旧仓严格。2019 年以前的回测基本读不到 M1、M2。
- 本仓库还没有 `ED_MoneySupply` 数据和派生因子，规则变更没有需要重算的对象。
  与旧仓 `macro_regime` 对拍时的差异以本 ADR 为解释。
