---
title: 聚源可见性：发布当天可见；货币供应取发布日与次月 15 日中较早者
status: active
created: 2026-11-23
updated: 2026-11-23
applies_to:
  - src/quantagent/contracts/visibility/
  - src/quantagent/contracts/spec.py
  - src/quantagent/domain/pit/
  - docs/domain/pit-rules.md
supersedes: adr/2026-11-23-ed-moneysupply-visibility.md
superseded_by: null
---
# 聚源可见性：发布当天可见；货币供应取发布日与次月 15 日中较早者

## 决策（负责人 2026-11-23 裁定）

1. **`InfoPublDate` 带时刻时，按日期比较，发布当天可见：** `InfoPublDate::date <= as_of`。
   适用于所有以 `InfoPublDate` 为可见日的聚源表。
   - 依据：CPI 在 09:30 发布，早于 A 股收盘；金十中国 CPI 与 Wind `ANN_DT` 的口径也是当天可见。
   - 与旧仓的差异：旧仓传 `'YYYYMMDD'` 给 SQL Server 比较 datetime，日期按 0 点算，
     当天带时刻发布的数据要到次日才可见。wx2 的 `C_ED_MacroIndicatorData` 里有 12,357 行
     发布日带时刻。对拍时这些行会早一天可见，以本条为解释。
2. **`ED_MoneySupply` 的可见日取两者中较早者：** `InfoPublDate` 的日期，和 `EndDate`
   次月 15 日（`EndDate` 都是月末，等于 `EndDate + 15` 天）。`InfoPublDate` 为空时直接用
   次月 15 日。可见日来自 `InfoPublDate` 的行等级为 A，来自次月 15 日的行等级为 B。
   本条取代[同日早些时候的裁定](2026-11-23-ed-moneysupply-visibility.md)（`InfoPublDate` 优先，空才回退）。
   - 依据：wx2 的 660 行里，`InfoPublDate` 晚于次月 15 日的有 427 行。其中 382 行晚 30 天以上，
     是 2019-05-17、2015-01-05 等批量回补日。另外 45 行晚 13 到 30 天，集中在 2019-07 至 2024-02，
     多落在次月月末，是聚源的录入日；人民银行通常在次月 10 日到 15 日发布。
     如果只用 `InfoPublDate`，2019 年以前的 M1、M2 要到回补日才可见。
   - 残余风险：次月 15 日不是法定截止日。人民银行如果某个月晚于 15 日发布，
     那个月会提前 1 到 2 天可见。所以这一支只给 B 级，rationale 里要写明。

## 契约表达

现有 `fallback` 的语义是"主字段为空才用"，表达不了"取较早者"。在 `VisibilitySpec` 加一个
可选字段 `fallback_mode: if_null | earliest`，默认 `if_null`，现有契约不受影响：

```yaml
visibility:
  rule: source_field
  field: InfoPublDate
  grade: A
  fallback_mode: earliest
  fallback:
    rule: fixed_lag
    field: EndDate
    lag_n: 15
    lag_unit: calendar_day
    grade: B
```

求解器逐行计算可见日：`LEAST(InfoPublDate::date, EndDate::date + 15)`，主字段为空时只看后一项。
读取时校验 `EndDate` 都是月末，不是就报错。返回行带上可见日来自哪一支，用于确定 `pit_grade`。
其余规则类型与组合仍然 fail-closed。

## 影响

本仓库还没有聚源数据和派生因子，规则变更没有需要重算的对象。
