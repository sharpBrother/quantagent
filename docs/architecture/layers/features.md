---
title: features 层职责
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/features/
---

# features：因子与特征面板

## 负责

| 子模块 | 职责 |
|---|---|
| `spec/` | `FeatureSpec` 声明式因子定义：输入依赖、参数、PIT lag、频率 |
| `library/` | 因子实现，按数据类型分域（price / fundamental / sentiment / macro） |
| `panel/` | 因子长表的计算编排与写入 |
| `metric/` | 因子评价指标计算与写入（IC、ICIR、覆盖率、多空收益、单调性、换手） |
| `registry/` | 因子定义与参数的旁置注册表读写（`var/lake/feature/_registry/`） |

## 不负责

| 排除项 | 正确归属 |
|---|---|
| 训练用宽矩阵物化 | `models.matrix` |
| 模型训练与预测 | `models` |
| 信号生成、回测 | `strategy` |
| 因子分组净值 | `strategy.backtest.vectorized`，因为它含执行语义 |
| 股票池成员物化、前瞻收益 | `lake` 的 `mart` 层，本层只读 |
| 因子健康度评级与阈值判定 | `publish`，阈值判定结果不是观测值 |
| 因子的可见性规则**定义** | `contracts/visibility/`；本层负责按规则推导 |

## 允许依赖

`platform`、`contracts`、`domain`。

注意：`features` 不直接依赖 `lake` 或 `adapters`，它通过 `domain.ports` 的
`Repository` Protocol 取数，具体实现由 composition root 注入。这样因子计算
的单测可以用 `adapters.memory`，完全不碰数据库和文件。

## 硬约束

### 长表是唯一格式

因子的交换与保存只有一种格式：`var/lake/feature/value/` 下的长表。身份分
三段——`feature_id`（语义身份）、`definition_version`（计算逻辑版本）、
`param_hash`（参数配置指纹）。配置全文存注册表，长表只存两个短字段。

详见 [../feature-storage.md](../feature-storage.md)。

### 评价指标是独立数据集，且不存在当日 IC

`metric/` 产出 `var/lake/feature/metric/`，键含 `(metric_id, window)` 两个
维度而不是每个指标一列。它的 `knowledge_dt` 取因子与 `forward_return` 可见
日的**较晚者**——`event_dt = T` 的 20 日 IC 要到 T+20 的收益可见后才能算
出，所以任何在 `as_of = T` 展示 `event_dt = T` 的 20 日 IC 的界面都是前视。

字段与推导规则见 [../derived-datasets.md](../derived-datasets.md)。

### knowledge_dt 与 pit_grade 不接受人工填写

- `knowledge_dt` 默认 = 所有输入 `knowledge_dt` 的最大值 + 因子自身计算
  延迟。因子可以声明更严格的规则，**不允许更宽松**。
- `pit_grade` 沿依赖图取最差值继承（木桶原理），**不可手工抬升**。

这两条是自动推导而非人工填写，目的是堵住「用低可信数据算出的因子被当作高
可信使用」。实现上，写入函数拒绝接受调用方传入的这两个字段值。

### 读取必须传 as_of

不存在无 `as_of` 的读取路径。只要提供一条便捷路径，它就会被用在需要 PIT
的地方。

## 典型反例

- **一因子一表**。旧仓 `factors/` 的 `stock_<factor>` 模式在运行时建表，
  造成表数量爆炸、跨因子 JOIN 昂贵、需要事后补覆盖索引
  （`docs/create_performance_factor_single_indexes.sql` 就是补救产物）。
- **只有一个 `feature_version`**。把算法版本和参数指纹合成一个字段，会让
  「换了参数」和「改了算法」无法区分，也无法分别回滚。
- **因子里内嵌 SQL**。旧仓 `factors/*.py` 与 `strategy/*.py` 内嵌 SQL 并
  自建 `DBConnect()`。因子只应该通过 `Repository` 取数。
- **在因子里做中性化然后落库**。原始因子值与中性化后的值是两个不同的
  `feature_id`（或同一 id 的不同 `param_hash`），不能把加工后的值当原始值
  存，否则下游无法还原。
- **计算延迟只在注释里说明**。因子的可见日延迟必须进声明，参与
  `knowledge_dt` 推导，不能靠使用方自己记得减几天。

## 对应的机械检查

- import-linter `只有 ingest 与 adapters 可以接触 PostgreSQL 驱动`：
  `features` 禁止 import `psycopg` 与 `sqlalchemy`。
- import-linter `业务层不得依赖 composition root`。
- `tests/contracts/`：长表 schema 校验、强制字段完整性、`pit_grade` 继承
  规则的推导测试（构造一个含 D 级输入的依赖图，断言输出为 D 级）。
