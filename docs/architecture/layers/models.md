---
title: models 层职责
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/models/
---

# models：建模抽象

## 负责

| 子模块 | 职责 |
|---|---|
| `dataset/` | `Dataset`：panel + label + 时间切分的组装 |
| `matrix/` | 训练用宽矩阵的物化与缓存（`var/lake/_matrix/`） |
| `splitters/` | `WalkForward`、`PurgedKFold` 等防泄漏切分 |
| `estimators/linear/` | WLS 中性化、截面 OLS 等线性实现 |
| `estimators/ml/` | LightGBM、神经网络等机器学习实现 |
| `pipeline/` | `CrossSectionalPipeline`、`TimeSeriesPipeline` |
| `evaluation/` | IC、RankIC、ICIR、分组收益，口径统一 |

## 不负责

| 排除项 | 正确归属 |
|---|---|
| 因子计算 | `features` |
| 交易信号、成本、账户 | `strategy` |
| 组合优化 | `portfolio` |

`model` 层产出的是**预测值**，不是仓位。从预测到仓位是 `strategy` 的职责。

## 允许依赖

`platform`、`contracts`、`domain`。取数同样经 `domain.ports`。

## 设计要点

线性模型与机器学习共用同一组抽象，这是「后续扩展到 ML」的落地方式：
`Estimator` 是 Protocol（`fit` / `predict`，兼容 sklearn API），现有的 WLS
和 OLS 只是它的一种实现。接 LightGBM 只需新增 `estimators/ml/`，`Dataset`、
`Splitter`、`Pipeline`、`Evaluation` 全部不动。

依赖分组上也做了显式切换：`pyproject.toml` 里 `ml` 是 optional extra，
不装它就跑不了 ML estimator。这让「当前只有线性模型」在依赖层面可见。

详见 [../modeling-extensibility.md](../modeling-extensibility.md)。

## 硬约束

- **宽矩阵与输入版本强绑定**。`matrix_id` 由 `feature_set_id`、
  `universe_id`、`date_range`、`as_of` 以及全部输入因子的
  `(definition_version, param_hash)` 计算得出。任一输入变化即换 id，旧缓存
  自然失效。
- **`_matrix/` 是纯缓存**。可整体删除重建，不是事实源，不入 git，不参与发布。
- **切分必须防泄漏**。标签窗口与特征窗口重叠时必须 purge/embargo，切分器
  的行为要有测试覆盖。

## 典型反例

- **每次训练全量 pivot**。长表到宽表的转换成本不小，不做缓存会让实验迭代
  变慢；但缓存不绑版本会更糟——参数改了还在用旧矩阵，错误是静默的。
- **把 `_matrix/` 当事实源**。一旦有人从缓存目录直接读数据做分析，缓存就
  不能随意删除了，它事实上变成了第二份因子存储。
- **模型产物没有身份**。落盘的模型必须带训练配置 digest、输入矩阵 id、
  代码版本。旧仓有 `signal_cache_*.pkl` 和 `day_result.pkl` 这类无身份的
  pickle，三个月后无法判断是哪次训练的产物。
- **用 pickle 存长期产物**。pickle 跨版本不稳定且不可读。模型权重用框架
  原生格式，元信息用 JSON。
- **评价口径各研究线自定义**。IC 的计算细节（是否剔除空值、用 pearson 还是
  spearman、分母口径）必须统一在 `evaluation/`，否则不同研究线的 IC 无法
  横向比较。

## 对应的机械检查

- import-linter `只有 ingest 与 adapters 可以接触 PostgreSQL 驱动`。
- import-linter `业务层不得依赖 composition root`。
- `tests/unit/models/`：切分器的防泄漏边界、`matrix_id` 的版本敏感性
  （改一个 `param_hash` 断言 id 变化）。
