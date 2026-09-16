---
title: 因子身份拆分为三段
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/features/
  - src/quantagent/models/matrix/
supersedes: null
superseded_by: null
---

# 因子身份拆分为三段

## 背景

长表需要一个因子身份字段。最简单的做法是一个 `feature_id` 加一个
`feature_version`。

但「版本」这个词掩盖了两件性质完全不同的事：

- **算法改了**：动量因子的实现从简单收益率改成对数收益率。这可能是修 bug，
  也可能是口径调整，通常需要重算全部历史并作废旧值。
- **参数改了**：动量窗口从 20 日改成 60 日。这是研究动作，新旧值应当共存
  以便比较。

合成一个字段后，这两件事无法区分，也无法分别回滚。

旧仓的 `alpha_factory_factor_value_d` 长表就缺这一层——它有因子名但没有
参数与算法版本的分离，因此"同一因子换参数"只能靠改因子名（`mom_20d` vs
`mom_60d`）表达，而"改了算法"完全无法表达。

## 决策

因子身份拆成三段，共同构成 `feature_key`：

| 字段 | 语义 | 变更触发 |
|---|---|---|
| `feature_id` | 「这是什么因子」，如 `mom` | 语义变了才换 |
| `definition_version` | 「怎么算的」 | 算法实现改变 |
| `param_hash` | 「用什么参数算的」 | 窗口、去极值阈值、中性化方案等参数改变 |

长表只存 `definition_version` 与 `param_hash` 两个短字段；配置全文与算法
元信息存旁置注册表：

```
var/lake/feature/_registry/
├── definitions/<feature_id>/<definition_version>.json
└── params/<param_hash>.json
```

`param_hash` 由参数集的规范化 JSON 计算（键排序、数值规范化），保证同一组
参数在任何机器上得到同一个 hash。

## 理由

1. **两类变更可分别追踪、分别回滚**。算法回滚不影响参数实验，参数实验不
   需要动算法版本。
2. **同一因子的多参数共存**。`mom` 的 20 日和 60 日是同一个 `feature_id`
   的两个 `param_hash`，可以同表共存并直接比较，不需要造两个因子名。
3. **长表不膨胀**。参数配置可能是几十个键的嵌套 JSON，塞进每一行不可接受。
   旁置注册表把它变成一次存储、多次引用。
4. **`matrix_id` 可以精确绑定**。宽矩阵与全部输入因子的
   `(definition_version, param_hash)` 绑定，任一变化即失效缓存。
5. **算法元信息有地方放**。注册表里可以存输入依赖、计算延迟、可见性规则
   引用、代码位置与 commit，这些都是长表放不下的。

## 被否方案

| 方案 | 否决理由 |
|---|---|
| 单一 `feature_id`，参数编进名字（`mom_20d`） | 参数组合多时名字爆炸；嵌套参数无法编码；无法表达算法版本 |
| `feature_id` + 单一 `feature_version` | 无法区分算法变更与参数变更，无法分别回滚 |
| 参数全文存长表 | 每行携带长 JSON，存储与查询成本不可接受 |
| 参数存 PG 注册表 | 派生数据不进 PG；且注册表应与因子数据同生命周期 |
| 四段或更多（再拆出数据源版本） | 数据源版本已由输入的 `knowledge_dt` 与 `pit_grade` 体现，再拆是过度设计 |

## 代价

1. **查询要带三个条件**。取一个因子的值需要同时指定
   `(feature_id, definition_version, param_hash)`，比单字段麻烦。通过
   `FeatureSpec` 解析为 `feature_key` 缓解，但接口层面是三个值。
2. **注册表是额外的一致性负担**。长表里有一个 `param_hash` 但注册表里没有
   对应条目，是一种可能的不一致。需要契约测试覆盖。
3. **`param_hash` 的规范化逻辑必须稳定**。如果规范化方式变了，同一组参数
   会得到不同 hash，历史数据的身份就断了。因此规范化逻辑本身要视为契约，
   变更需要 ADR。
4. **`definition_version` 靠人维护**。改了算法但忘了升版本，会让新旧值混
   在同一身份下。这是无法完全机械检测的（代码 diff 不等于算法变更），只能
   靠 review。

## 推论

1. **`param_hash` 的规范化方式是契约的一部分**，记在注册表的元信息里。
   变更需要 ADR 并重算全部历史。
2. **改算法必须升 `definition_version`**。code review 的检查项。判断标准：
   同一输入同一参数下输出会变，就是算法变更。
3. **`feature_id` 的语义边界要在 `FeatureSpec` 里写清**。什么程度的变化
   算"还是同一个因子"，需要逐因子判断，不能靠通用规则。
4. **注册表与长表同生命周期**。`_registry/` 在 `var/lake/feature/` 下，
   与因子数据一起备份、一起迁移，不单独管理。
