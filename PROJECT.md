# QuantAgent 项目说明

## 项目愿景

QuantAgent 是一个个人维护、以研究证据为基础、以 Agent 为组织方式的 AI 量化
投研项目。它优先服务于快速实现、快速验证和可解释的研究迭代，**不以建设
企业级平台、长期运营服务或正式交易系统为默认目标**。

本仓库是 `pycharm_workspace` 的重构版本。重构的动因不是"代码写得不好"，
而是四类结构性问题已经开始产生真实的维护成本：数据分层与程序分层都不清晰、
时间语义（PIT）靠读取时过滤而非规则声明、脚本与文档失去归属、工程基建缺位。

完整的诊断与设计见 [`docs/architecture/overview.md`](docs/architecture/overview.md)。

## 项目定位

**AI Quant Research Lab（AI 量化研究实验室）。**

不属于：个人博客、金融资讯网站、股票论坛、交易软件。

参考风格：OpenAI、Bloomberg Terminal、Vercel、Linear。

长期愿景是逐步形成 AI Quant Operating System（AI 量化投研操作系统）；这不是
当前已完成的产品承诺。

## 目标用户

主要：投资者、基金经理、投顾、金融工程师、量化研究员。

次要：AI Agent 开发者、金融科技从业者、量化爱好者。

---

# 项目原则

## 研究优先

所有展示内容必须来源于实际研究成果。

## 时间语义优先

这是本次重构提升到第一优先级的原则。

业务时间、来源发布时间、系统采集时间是三条独立的轴，**三者都不是 PIT**。
可见日由声明式规则计算得出。每个数据集与每个因子都必须声明自己的可见性
规则，规则缺失是唯一 fail-closed 的情形。

因子的 `knowledge_dt` 与 `pit_grade` 由血缘自动推导，不接受人工填写。

见 [`docs/domain/temporal-semantics.md`](docs/domain/temporal-semantics.md)
与 [`docs/domain/pit-rules.md`](docs/domain/pit-rules.md)。

## 契约优先，不用文档式数据字典

数据集 schema、发布产物 schema、可见性规则都是可执行的，在 CI 中运行。
旧仓 `docs/data_dictionary/` 的 318 张表字典是文档，无法阻止实现漂移。

见 [`docs/contracts/README.md`](docs/contracts/README.md)。

## 口径与实现分离

`domain/` 是纯规则层，零存储依赖，能在没有数据库和文件的条件下完整单测。
读取接口以 Protocol 形式定义在 `domain/ports/`，`adapters/` 提供三套实现。

代价是多一层间接，收益是：换存储、迁数据库、调分区布局都只动适配器。

见 [`docs/architecture/ports-and-adapters.md`](docs/architecture/ports-and-adapters.md)。

## 分层是职责划分，不是强制管线

数据层定义"我负责什么、我可以依赖谁"，研究线按需取用。宏观指标展示不必
穿过因子层，因子评价不必穿过组合层，规则策略不必穿过模型层。

只有两条硬约束：不得反向依赖、不得同层成环。跨层直读允许，但必须在资产
契约里声明 `reads:`，让血缘图可见。

见 [`docs/architecture/data-layers.md`](docs/architecture/data-layers.md)。

## 证据优先与发布边界

研究结果、展示快照和生产信号不是同一种东西。进入展示层的内容至少要能说明
来源、数据截止日、代码或运行身份、生成路径，以及 PIT 可信度
（`pit_report`）。缺少关键身份或验证证据时保持研究状态，不向下游晋升。

回测、paper、生产和研究诊断保持语义隔离。**Agent 观点、回测结果、组合建议
都是研究展厅内容，不是生产仓位，不自动授权交易执行。**

## Agent 优先与可解释

Agent 是系统的重要组成部分。每个 Agent 输出观点、依据与不确定性。所有观点
都应提供解释逻辑，无法解释的输出不发布。

## 简约设计

避免信息过载。

## 最短路径与执行不漂移

从当前目标到可验证结果，优先选择最短、最小、可回滚的实现路径。不为未来
场景预建框架、服务、表、接口或跨模块抽象；无关改进记录为后续候选。

目标、非目标、数据口径、修改范围和验收标准一经说定，执行过程中不得静默
改变。具体 Agent 行为规则见 [`AGENTS.md`](AGENTS.md)。

## 不建设治理仪式

本项目由一个人维护，运行者、决策者和审阅者是同一个人。任何要求这个人向
自己出示授权的机制都是纯开销，不得建设：数据库主体身份匹配、授权过期、
书面授权 digest、审批角色分离、execution ledger、不可变 receipt 链、文档
编号台账、多段式评审流程。

需要区分的是：**防止数据被写坏**和**防止研究结论不成立**的检查不属于治理
仪式，必须保留并加强。见 `AGENTS.md` §6 与 §7。

## 工程基建是必需的，不是治理仪式

这一条是本次重构新增的。旧仓无 `pyproject.toml`、无 lint、无类型检查、
CI 只跑 2 个 unittest，导致"项目不可安装、依赖不可复现、分层无法强制"。

这些不是流程开销——它们的作用正是"防止数据被写坏"和"防止研究结论不成立"。
`import-linter` 防止绕过读边界，`mypy` 防止类型错误进入计算，契约测试防止
口径漂移。

---

# 技术约束

## Python 版本

**Python 3.12，唯一基线。** `requires-python = ">=3.12,<3.13"`。

旧仓被 SQL Server 驱动锁在 3.8/3.9（文档声明 3.8、开发机跑 3.9、而 136 个
文件已在用 PEP585 泛型）。迁到 PostgreSQL + psycopg3 后这个约束消失：
psycopg3 的 binary 包自带预编译 libpq，不依赖系统 ODBC，不需要 JDBC 桥接
和 JVM。

取舍记录见
[`docs/adr/2026-09-16-python-312-baseline.md`](docs/adr/2026-09-16-python-312-baseline.md)。

## 工具链

| 项 | 选择 |
|---|---|
| 依赖与虚拟环境 | uv，锁在 `uv.lock` |
| 项目形态 | 可安装包，`src/` 布局，hatchling |
| lint + format | ruff |
| 类型检查 | mypy strict |
| 测试 | pytest，四类分层（unit / contracts / golden / integration） |
| 依赖方向 | import-linter |
| 提交门禁 | pre-commit |
| 编排 | Dagster |
| CLI | Typer |

任何 import 的包必须出现在 `pyproject.toml` 的某个依赖组里。

## 存储

| 用途 | 选型 |
|---|---|
| 源数据原生镜像 | PostgreSQL `src_*` schema |
| 控制状态（调度、水位、运行日志） | PostgreSQL `ops_*` schema |
| 派生事实（std / mart / feature / model / signal / portfolio） | Parquet，`var/lake/` |
| 查询引擎 | DuckDB，不持久化 `.duckdb` |
| 冻结输入制品 | `frozen/`，入 git |
| 发布产物 | `publish/`，入 git |

`var/` 整体 gitignore。入 git 的数据目录只有 `frozen/` 与 `publish/`。

选型理由与被否方案见
[`docs/adr/2026-09-16-storage-selection.md`](docs/adr/2026-09-16-storage-selection.md)。

## 入口

只有两处：`quantagent <group> <command>`（Typer）和 Dagster asset/job。
**没有 `scripts/` 目录**，pre-commit 与 CI 都会拦。探索性代码进
`notebooks/` 并有过期规则。

## 前端

`apps/web/` 使用独立的 Node / TypeScript / Next.js 工具链，版本以本目录的
`package.json` 为准，与 Python 侧无关。前端只读 `publish/*.json`，不直连
数据库，不反向写入。

## 远端任务计划配置边界

远端 Windows Task Scheduler 由项目负责人手工维护。Agent 不通过 SSH、RDP、
任务计划 API 或其他远端管理方式修改远端任务；需要调整时只提供操作步骤、
应保留的触发器/账户/工作目录/命令参数，以及完成后的核验命令。

---

# 核心模块

## Agent Dashboard

| Agent | 负责 |
|---|---|
| 宏观 | 信用周期、流动性、利率、宏观环境判断 |
| 债券择时 | 利率债指数多空（相对现金） |
| 黄金择时 | 黄金价格指数多空（相对现金） |
| 风格轮动 | 成长、价值、红利、小盘、大盘 |
| 行业轮动 | 行业强弱排序、行业景气度 |
| 风控 | 波动率、风险水平、拥挤度 |
| 组合 | 仓位管理、配置建议 |

所有 Agent 观点都是研究展厅内容，不是生产仓位。

## 策略商城

展示通过发布选择进入展示层的策略快照，不等同于全部策略，也不等同于实盘
交易能力。每个策略含简介、收益率、夏普、最大回撤、净值曲线、当前持仓、
Agent 点评，以及 `pit_report`。

回测、paper 和其他运行类型保持独立身份；展示的运行结果必须能追溯到明确的
`run_id`、数据截止日和代码版本。

## Portfolio OS

快照形式展示当前资产配置、风险贡献、Agent 投票结果、当前组合观点。

展示结果是研究和配置观点的可视化，不自动授权交易执行或生产调仓。

## Alpha Factory

Alpha 因子库、IC、RankIC、ICIR、Turnover、Decay。因子长表是唯一事实源，
见 [`docs/architecture/feature-storage.md`](docs/architecture/feature-storage.md)。

## 风格因子择时

因子动量、拥挤度、离散度、排名。

## Research Lab

研究文章及其结构化元数据，按宏观研究、因子研究、Alpha 研究、Agent 研究、
市场观察分类。

## 首页

当前市场状态、Agent 运行状态、最新研究成果、最新策略表现。

---

# 数据来源

| 源 | 内容 |
|---|---|
| Wind | 量价、基本面 |
| Tushare | 行情、财务 |
| 朝阳永续 | 分析师一致预期 |
| 聚源 JYDB | 基础数据 |
| FRED / 金十 / WGC | 宏观与贵金属 |

数据缺失、版本不明或身份无法对齐时，相关结果保持为不可晋升状态。

旧 SQL Server 库 `wx2` 在迁移期作为只读源，处置标准见
[`docs/migration/wx2-disposition.md`](docs/migration/wx2-disposition.md)。

---

# 当前阶段

**P1 底座已形成，P2 已产出 wx2 逐表处置清单；存量迁入尚未开始。**

截至 2026-09-18，代码已包含 platform（配置 / 路径 / digest / run log /
写闸）、PG 双面迁移文件与迁移命令、源镜像写入保护、Tushare 交易日历采集
与 std 物化、因子布局 benchmark，以及日历、因子值、股票池成员、前瞻收益、因子指标、
分组净值的带 `as_of` 读取接口和相应测试。

这说明代码能力已落地，不代表所有 PG 迁移、真实数据采集与阶段验收都已完成。
因子计算、模型、回测内核、Agent、publish 与 Dagster 编排仍以骨架为主，
`apps/web/` 尚未实现，完整研究到静态展厅的链路尚未贯通。

阶段划分、每阶段验收标准与回滚点见
[`docs/migration/roadmap.md`](docs/migration/roadmap.md)。

## 默认非目标

- 不为未来可能的多资产、实盘、服务化或多租户需求，提前增加完整平台架构
- 不把一次性研究脚本强行改造成通用框架、插件系统或复杂领域模型
- 不因单个局部需求擅自新增服务、数据库表、公共接口、配置体系或基础设施
- 不把研究结果包装成未经验证的生产能力或交易能力
- 不建 AutoML 框架、模型注册中心、实验追踪平台
- 不预建深度学习基础设施（扩展点已留好，有真实需求再加）

## 后续候选方向

长期路线，不是当前范围。进入实施前必须有明确需求、架构基线和验收标准。

- Agent 可视化深化：Agent 状态、解释、证据、历史变化
- 组合智能决策：在组合数据口径、风险约束明确后逐步完善
- AI 投研助手：在研究证据、权限边界和真实消费者明确后再评估。当前只允许
  受控内部原型，不进入正式产品建设
- AI Quant Operating System：长期愿景，不提前建设完整企业级平台
