# QuantAgent

个人维护的 AI 量化投研系统。数据从外部源进入 PostgreSQL 源镜像层，经
Parquet Lakehouse 完成标准化、口径对齐、因子计算、建模、信号与组合，最终
装配为发布产物供展示层消费。DuckDB 作查询引擎，Dagster 作资产化编排。

重构自 `pycharm_workspace`。**当前处于 P1 第一刀：platform 底座、契约加载
与交易日历契约已落地；尚未接 PostgreSQL，也尚未采集数据。**

## 先读这三份

| 文档 | 内容 |
|---|---|
| [PROJECT.md](PROJECT.md) | 项目定位、原则、技术约束 |
| [AGENTS.md](AGENTS.md) | 工作规则、数据安全铁律、研究正确性铁律 |
| [docs/README.md](docs/README.md) | 唯一文档入口 |

## 快速开始

```bash
# 安装依赖（uv 会自动装 Python 3.12）
uv sync --all-extras --dev

# 配置
cp .env.example .env    # 填写连接参数与凭据；.env 永不入库

# 质量门禁
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run lint-imports              # 依赖方向契约
uv run pytest -m "unit or contracts"
uv run quantagent check contracts
uv run quantagent db status      # 第一刀不连库；未配置会打印「未配置」

# 提交钩子
uv run pre-commit install
```

## 目录结构

```
quantagent/
├── docs/                 设计文档、ADR、口径与契约、迁移路线
├── src/quantagent/
│   ├── platform/         配置、日志、run log、digest、DuckDB 会话
│   ├── contracts/        可执行契约：schema 与可见性规则 YAML
│   ├── domain/           口径规则（零存储依赖）+ ports Protocol
│   ├── adapters/         postgres / lake / memory，实现 domain.ports
│   ├── ingest/           外部源到 PG 研究数据面（唯一写 PG 的层）
│   ├── lake/             Parquet 物化与读取
│   ├── features/         因子与特征面板（长表）
│   ├── models/           Dataset / Splitter / Estimator / Evaluation
│   ├── strategy/         信号、成本、回测（合同 + 三类内核）
│   ├── portfolio/        组合构建、风险、归因
│   ├── agents/           研究 Agent 与观点组织
│   ├── publish/          发布产物装配
│   └── cli/              统一命令行入口
├── orchestration/        Dagster asset / job / schedule / resources
├── db/                   PG 迁移（src 与 ops 两条独立序列）
├── tests/                unit / contracts / golden / integration
├── notebooks/            探索性分析的唯一去处（jupytext 配对）
├── apps/web/             Next.js 展示层（P5）
├── frozen/               入库的冻结输入制品（只读，带 manifest）
├── publish/              入库的发布产物 JSON
└── var/                  gitignore：lake、缓存、日志、运行制品
```

每层的职责定义（负责什么、不负责什么、允许依赖、典型反例）在
[docs/architecture/layers/](docs/architecture/layers/)。

## 六条设计原则

1. **分层是职责划分，不是强制管线**。只有两条硬约束：不得反向依赖、不得
   同层成环。跨层直读允许但必须声明 `reads:`。
2. **口径规则与存储实现彻底分离**。`domain/` 零存储依赖，读取经 Protocol，
   换存储只动适配器。
3. **时间语义必须显式声明**。业务时间、发布时间、采集时间是三条独立的轴，
   三者都不是 PIT。可见日由声明式规则计算得出。
4. **契约是代码，不是文档**。schema 与可见性规则在 CI 中执行。
5. **入口只有两处**。CLI 子命令与 Dagster asset，**没有 `scripts/`**。
6. **机械检查只覆盖可机械检查的部分**。职责定义靠文档，工具管依赖方向、
   风格、类型和行为口径。

## 两条铁律不可删除

- **数据安全**：默认不写库、目标表白名单、SQL 动词白名单、不覆盖既有行、
  写后回读、事务状态未知不重试。
- **研究正确性**：PIT 无前视、可见性规则不得缺失、PIT 字段不得人工填写、
  采集时间不是发布时间、不填充不跨日池化、分母口径固定、fail-closed、
  结果可复现、PIT 信息不得隐藏、不在重构中顺手改口径。

完整表述见 [AGENTS.md](AGENTS.md) §6 与 §7。

## 边界声明

Agent 观点、回测结果、组合建议都是**研究展厅内容，不是生产仓位，不自动
授权交易执行**。可视化能力不等于生产决策能力。
