---
title: 迁移路线 P0–P6
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - src/quantagent/
  - orchestration/
  - db/
  - frozen/
  - apps/web/
---

# 迁移路线 P0–P6

## 策略：strangler，不是大爆炸

旧仓 `pycharm_workspace` 在整个迁移期保持运行。新系统逐层接管，每接管一块
就把对应的旧调用切过来，直到旧仓无消费者才封存。

不采用"停下来重写再切换"，因为研究是持续进行的，停机成本不可接受；也因为
一次性切换的失败无法局部回滚。

## 阶段总览

| 阶段 | 内容 | 关键产出 |
|---|---|---|
| P0 | 骨架 | 目录结构、工程基建、设计文档 |
| P1 | 存储底座与时间语义 | PG 双面 schema、DuckDB 会话层、契约校验、因子布局 benchmark、`_vintage/` 归档启动 |
| P2 | 处置清单与数据入湖 | wx2 逐表清单、ETL 重写为 asset、发布时间可得性盘点 |
| P3 | 口径与因子 | domain 纯规则层、ports/adapters、golden test、因子长表 |
| P4 | 建模与策略 | Dataset/Estimator 抽象、回测语义合同、内核对照 |
| P5 | 发布与前端 | 冻结制品迁入、publish 契约、apps/web |
| P6 | 旧仓封存 | pycharm_workspace 转只读归档 |

---

## P0 骨架（本次交付）

### 内容

仓库初始化、工程基建配置、设计文档。不写任何业务逻辑代码。

### 验收标准

- `uv sync` 成功，`uv run ruff check .`、`uv run mypy`、
  `uv run lint-imports` 全部通过（当前无代码，等于验证配置本身有效）
- 目录骨架完整，每个分层包的 `__init__.py` 有职责 docstring
- `docs/` 下所有文档 frontmatter 完整
- `.gitignore` 十几行，`var/` 整体忽略，`frozen/` 与 `publish/` 入库

### 回滚点

无需回滚——P0 不触碰旧仓任何内容。

---

## P1 存储底座与时间语义

### 内容

1. PG 双面 schema 建立（`db/migrations/src/` 与 `db/migrations/ops/`）
2. `platform/` 的配置、日志、run log、digest、DuckDB 会话层
3. `contracts/` 的 schema 与 visibility 规则加载与校验
4. **因子长表物理布局 benchmark**：分区键、目标文件大小、排序键、压缩，
   出 ADR 后才固化 Parquet 约定
5. **批次快照归档启动**（`var/lake/_vintage/`）

### 为什么 benchmark 在这里

物理布局一旦固化，改起来要重写全部历史数据。在写入任何真实因子之前完成
benchmark，代价最低。

### 为什么 `_vintage/` 归档在 P1 而不是 P2

越早开始积累，收益越大——每晚一天就永久少一天的版本序列。它不依赖数据
入湖完成，只依赖采集能跑，因此与存储底座一起启动。见
[../adr/2026-09-16-no-source-vintage-in-pg.md](../adr/2026-09-16-no-source-vintage-in-pg.md)。

### 验收标准

- 两条迁移序列可独立 `migrate` 与 `status`
- DuckDB 会话能挂载 Parquet 并跑通三类代表性查询
- 至少一个数据集有完整契约（schema + visibility + `reads`），且缺规则时
  CI 确实失败
- benchmark 结论 ADR 已定版，脚本保留在仓库
- `_vintage/` 有第一个批次快照落盘，格式符合契约

### 回滚点

PG schema 可整体 drop 重建（此时无真实数据）。`var/lake/` 可整体删除。
不影响旧仓。

---

## P2 处置清单与数据入湖

### 内容

1. **先产出 `wx2` 逐表处置清单**（见 [wx2-disposition.md](wx2-disposition.md)）
2. 按类别分别执行：源数据迁 `src_*`，派生数据不迁，不可重算历史冻结到
   `var/lake/legacy/`，控制状态重新建模到 `ops_*`，无消费者不迁
3. Wind / Tushare / JYDB / 朝阳永续 / 宏观 ETL 重写为 Dagster asset
4. **逐源逐表完成发布时间可得性盘点**，为每个数据集定版 visibility 规则
   与 `pit_grade` / `pit_from`
5. 文档与制品处置清单产出（执行在 P5，但清单要在这里完成）

### 顺序约束

**清单未完成前不启动任何迁移动作。** 先迁一部分再定清单，会出现"已经迁
进来但发现应该不迁"，而删除已迁入的数据比一开始不迁麻烦得多。

### 验收标准

- 每张 `wx2` 表都在清单中有归属与判定依据，无归属的表为零
- 每个迁入的数据集有 visibility 规则，`grade` 与 `rationale` 齐全
- 存量迁入的数据集全部标注 `pit_recoverable: false` 与 `pit_from`
- `std` 与 `mart` 层有第一批资产可物化，血缘图完整
- 写入保护的六条约束各有测试覆盖且通过
- 文档与制品清单完成（用于保护冻结制品不被误删）

### 回滚点

`src_*` 可按表 drop 重新迁入（源数据可重新拉取）。`var/lake/legacy/` 冻结
后不可重建——因此它的迁入要在清单定版之后，且迁入前做一次独立备份。

旧仓在此阶段仍是权威，任何不一致以旧仓为准。

---

## P3 口径与因子

### 内容

1. `domain/` 纯规则层落地：calendar、adjust、identity、pit、universe、
   classification
2. `domain/ports/` 的 Protocol 与三套适配器
3. **先把旧仓口径固化成 golden test**：`BaseDataGateway`、
   `UniverseProvider`、`MarketDataService` 及各研究线网关
4. 新实现对拍通过
5. `feature` 长表与 `knowledge_dt` / `pit_grade` 血缘推导
6. `factors/` 与 `alpha_factory/` 的因子移植

### 顺序约束

**golden test 先于新实现。** 顺序颠倒的话，新实现的行为会变成基线，口径
漂移无从发现。

### 验收标准

- `tests/unit/domain/` 全部在零数据库零文件条件下通过
- `tests/contracts/` 三套适配器行为一致
- `tests/golden/` 覆盖旧仓四类网关的口径，差异全部有解释并记入 ADR
- 因子长表写入时拒绝人工传入 `knowledge_dt` 与 `pit_grade`
- `pit_grade` 木桶继承有测试：构造含 D 级输入的依赖图，断言输出为 D
- 不存在无 `as_of` 的读取路径（接口层面校验）
- 重算的因子与旧库交叉校验完成，差异有解释

### 回滚点

因子可重算，整层可删除重建。domain 与 adapters 是纯代码，git revert 即可。

此阶段开始出现"新旧并行"：同一个因子新旧两份值。以旧仓为权威直到交叉校验
通过。

---

## P4 建模与策略

### 内容

1. `Dataset` / `Splitter` / `Estimator` / `Pipeline` / `Evaluation` 抽象
   落地，WLS 与截面 OLS 迁入 `estimators/linear/`
2. **先定版回测语义合同**并让各内核输出统一结果 schema
3. `rebalance` 内核（继承 `BacktestEngine` 语义）
4. `vectorized` 内核（继承 `group_backtest` 语义）
5. 用行为对照测试逐对判定是否合并
6. 策略与 Agent 移植

### 顺序约束

**合同先于内核。** 没有统一的结果 schema，"行为一致"连比什么都说不清。
见 [../adr/2026-09-16-backtest-contract-first.md](../adr/2026-09-16-backtest-contract-first.md)。

### 验收标准

- 回测语义合同四部分全部有可执行 schema
- 三类内核（`event` 可暂缺）输出同一套结果 schema，含 `pit_report` 与
  `diagnostics`
- 与旧 `BacktestEngine` 的行为对照通过，容差显式设定
- `GenericSelectionBacktest` 的去留有明确判定与依据
- 缺价不填充有测试覆盖
- `matrix_id` 的版本敏感性有测试：改一个 `param_hash` 断言 id 变化
- 切分器的 purge/embargo 边界有测试

### 回滚点

回测结果可重算。合同定版后若发现需要修改，走 ADR 流程并重算受影响的结果。

---

## P5 发布与前端

### 内容

1. **冻结输入制品迁入 `frozen/`** 并接上契约校验
2. `publish` 契约与装配器
3. `apps/web` 从旧 `website/` 迁移
4. 文档与制品处置清单执行（清单在 P2 已完成）

### 验收标准

- `tests/contracts/test_frozen_bundles.py` 对所有迁入 bundle 通过：manifest
  完整、digest 一致、行列合同符合
- bond_timing bundle 的 digest 在迁移后仍然校验通过（证明迁移没改内容）
- 每个发布产物携带 `pit_report` 与运行身份
- 前端确实展示 PIT 等级，不折叠进"更多信息"
- 展厅刷新链路端到端跑通，冻结前缀未被重算
- 旧 `website/` 的 schema 校验与 e2e 已迁移并通过

### 回滚点

`publish/` 可重新装配。`frozen/` 迁入前旧仓仍保有原件，迁入后 digest 校验
失败即回退到旧仓版本重新迁移。

---

## P6 旧仓封存

### 前置条件

三份清单中所有「迁入」项已落地，且契约测试通过：

- [../architecture/legacy-inventory.md](../architecture/legacy-inventory.md)
  的提炼/移植项
- [wx2-disposition.md](wx2-disposition.md) 的第一、三、四类
- [docs-and-artifacts-disposition.md](docs-and-artifacts-disposition.md)
  的第一、二、三类

以及：旧调度项逐条对应到新 asset，对应关系记录完成。

### 内容

`pycharm_workspace` 转只读归档。保留 git 历史作为事实追溯来源。

### 验收标准

- 旧仓零写入操作持续一个完整业务周期（含月末、季末、财报季）
- 新系统独立完成一轮完整的月度发布
- 旧调度全部关停，无任务失败告警
- 三份清单中"不迁移"的项都有判定依据与旧仓 commit 指针

### 回滚点

这是最后一个可回滚点。封存后旧仓仍可读，但恢复写入需要重新配置环境
（SQL Server 驱动、Python 3.9 环境），成本较高。因此封存前的验收标准要
严格执行，尤其"持续一个完整业务周期"这条不能压缩。

---

## 贯穿全程的原则

1. **旧仓是权威，直到对拍通过**。任何新旧不一致，先假定新实现有问题。
2. **不在迁移中顺手改口径**。发现旧口径有问题，记 ADR 单独处理，不混在
   迁移里。
3. **每阶段的验收标准是硬门槛**，不通过不进下一阶段。
4. **清单先于执行**。三份清单都是这个模式——先定性，再动手。
5. **golden test 与合同先于实现**。它们定义了什么叫"正确"。

## 进度维护

本文档是活文档。阶段完成后在这里标注，不另建进度台账。阶段内容需要调整时
直接改本文档；如果调整涉及设计取舍，在 `docs/adr/` 记一份。
