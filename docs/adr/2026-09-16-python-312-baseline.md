---
title: Python 3.12 作为唯一基线
status: active
created: 2026-09-16
updated: 2026-09-16
applies_to:
  - pyproject.toml
  - .python-version
  - .github/workflows/ci.yml
supersedes: null
superseded_by: null
---

# Python 3.12 作为唯一基线

## 背景

旧仓的 Python 版本状况是长期的隐性负担：

- 文档与配置声明 Python 3.8
- 开发机实际跑 3.9（`miniforge3/envs/py39arm`）
- 而 136 个文件已经在用 PEP585 泛型（`list[str]` 而非 `List[str]`），这在
  3.8 下会报错
- 无 `pyproject.toml`，项目不可安装，417 个文件靠 `sys.path.insert` 运行
- 依赖不锁版本，`pymssql` 在 prod 与 CI 版本不一致
- matplotlib、scipy、pytest、selenium 等实际 import 的包从未声明

版本被锁在 3.8/3.9 的直接原因是 SQL Server 驱动的兼容性——公司 Windows 侧
的 ODBC 驱动与 `pymssql` 版本组合限制了 Python 版本。

迁到 PostgreSQL 后这个约束消失：psycopg3 的 binary 包自带预编译 libpq，
不依赖系统 ODBC，也不需要 JDBC 桥接和 JVM。

## 决策

**Python 3.12 是唯一基线。** `requires-python = ">=3.12,<3.13"`。

配套的工程基建：

| 项 | 选择 |
|---|---|
| 依赖与虚拟环境 | uv，依赖锁在 `uv.lock` |
| 项目形态 | 可安装包，`src/` 布局，hatchling 构建 |
| lint + format | ruff（含 `UP` 规则，强制 3.12 惯用写法） |
| 类型检查 | mypy strict |
| 测试 | pytest，四类分层 |
| 依赖方向 | import-linter |
| 提交门禁 | pre-commit |

## 理由

1. **驱动约束已消失**。这是原来无法升级的唯一硬原因。
2. **代码实际已在用 3.9+ 特性**。声明 3.8 只是文档与现实脱节，统一到 3.12
   是把既成事实写正。
3. **3.12 的类型系统改进有实际价值**。PEP 695 的泛型语法、更好的错误信息、
   `Self` 类型，对 Protocol 密集的架构（`domain/ports`）有帮助。
4. **性能**。3.11/3.12 的解释器优化对纯 Python 的数据处理循环有可观收益。
5. **单一版本消除"两套语义"**。开发机与生产同版本，不存在"本机能跑线上
   报错"。
6. **uv 的锁文件让依赖可复现**。旧仓的 `pymssql` 版本不一致问题不会再有。

选 3.12 而不是 3.13：3.12 的第三方库生态（pandas、pyarrow、duckdb、
dagster、lightgbm）已经完整，3.13 在本项目所需的科学计算栈上还有零星缺
口。上限锁 `<3.13` 是为了让升级成为显式动作。

## 被否方案

| 方案 | 否决理由 |
|---|---|
| 留在 3.9 | 驱动约束已消失，没有留下的理由；且 3.9 已接近 EOL |
| 升到 3.13 | 部分科学计算库尚未完整支持；收益不足以承担风险 |
| 多版本支持（3.10–3.12） | 单人项目，多版本测试矩阵是纯成本；且会阻止使用新语法 |
| poetry / pdm / pip-tools | uv 速度快一个量级，且同时管虚拟环境与 Python 版本安装 |
| conda / mamba | 环境体积大、锁文件生态弱；本项目不需要非 Python 的原生依赖 |
| black + isort + flake8 | ruff 一个工具覆盖三者且快得多 |

## 代价

1. **公司 Windows 侧需要装 3.12**。uv 可以自己安装 Python，因此不依赖系统
   包管理，但仍是一次部署动作。
2. **mypy strict 有前期成本**。所有函数要写类型注解（ruff 的 `ANN` 规则也
   会要求）。这在写新代码时是习惯问题，在迁移旧代码时是真实工作量。
3. **锁版本意味着定期升级维护**。`uv.lock` 需要主动更新，不会自动跟进
   上游。
4. **上限 `<3.13` 需要主动放宽**。这是刻意的——让升级经过评估。

## 推论

1. **不再需要 JDBC / JVM**。旧仓 12 个 JVM 崩溃日志的成因随之消失，
   `dbconnect.py` 里的 DBeaver jar 路径与 JVM 路径也不再需要。
2. **项目必须可安装**。入口通过 `project.scripts` 注册（`quantagent`
   命令），不允许 `sys.path.insert`。
3. **任何 import 的包必须出现在某个依赖组里**。这是 code review 的检查项，
   也是旧仓"实际依赖未声明"问题的根治方式。
4. **ruff 的 `UP` 规则强制 3.12 惯用写法**。不允许 `typing.List` 这类过时
   写法与新代码混存。
5. **ruff 的 `PTH` 规则强制 pathlib**。配合 `platform` 的路径解析，杜绝
   旧仓 88 个文件写死 `/Users/le` 那类问题。
6. **CI 用 `UV_FROZEN=1`**。锁文件与 `pyproject.toml` 不一致时 CI 失败，
   不自动更新锁。
