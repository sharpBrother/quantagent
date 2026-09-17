---
title: cli 层职责
status: active
created: 2026-09-16
updated: 2026-09-17
applies_to:
  - src/quantagent/cli/
---

# cli：统一命令行入口

## 负责

- **命令分组与参数解析**：`quantagent <group> <command>`，Typer 实现。
- **composition root**：把 `adapters` 的具体实现注入到业务层依赖的
  `domain.ports` Protocol。
- **命令索引**：`quantagent --help` 是「有哪些能力」的权威答案。

## 不负责

任何业务逻辑。CLI 子命令的函数体应该只做三件事：解析参数、组装依赖、调用
业务函数。如果子命令里出现了循环和条件判断构成的业务流程，说明业务逻辑该
往下沉。

## 允许依赖

全部层（composition root 的特权）。反之业务层不得 import `cli`。

## 硬约束：没有 scripts/ 目录

所有可执行入口只有两处来源：本层的 CLI 子命令，和 `orchestration/` 的
Dagster asset/job。探索性代码进 `notebooks/`。

pre-commit 与 CI 都会拦 `scripts/` 目录的出现。

理由见 [../cli-and-orchestration.md](../cli-and-orchestration.md)。简单说：
旧仓 `scripts/` 有 316 个脚本，只有约 8% 是长期入口，约 81% 既不在调度也
不在现役文档中。这不是纪律问题——是因为「一段可执行代码该往哪放」没有
答案，于是全都放进了 `scripts/`。

## 命令分组

分组按**动作对象**而非按模块划分，因为使用者找命令时想的是"我要刷新因子"
而不是"我要调用 features 模块"：

```
quantagent ingest tushare trade-cal  交易日历采集
quantagent lake benchmark-layout  因子长表布局 benchmark
quantagent lake materialize trade-calendar  交易日历标准化物化
quantagent feature <action>     因子计算与注册表
quantagent model <action>       训练与预测
quantagent backtest <action>    回测
quantagent portfolio <action>   组合与风险
quantagent publish <action>     发布装配
quantagent db <action>          迁移
quantagent check <action>       契约与一致性校验
```

## 典型反例

- **在 CLI 里写业务流程**。子命令膨胀成几百行是信号：业务逻辑写在了入口层，
  无法被测试也无法被 Dagster 复用。
- **CLI 与 Dagster 各写一遍逻辑**。两者都是 composition root，应该调用同一
  组业务函数。旧仓的 `scripts/*.py` 与 `task_scheduler` 调度的
  `scripts/schedule/*.bat` 之间存在这种重复。
- **靠 `sys.path.insert` 让脚本能跑**。旧仓 417 个文件这么做。项目必须是
  可安装的包，入口通过 `project.scripts` 注册。
- **中文文件名**。旧仓有 `data/情绪择时推送.py`。命令名与模块名用英文，
  帮助文本用中文。
- **写库默认开启**。任何涉及写入的子命令，`--write-db` 默认关闭，且需
  `QUANTAGENT_ALLOW_DB_WRITE=true` 双重确认。

## 对应的机械检查

- import-linter `业务层不得依赖 composition root`：`domain` / `features` /
  `models` / `strategy` / `portfolio` / `agents` 禁止 import `cli`。
- pre-commit `no-scripts-dir` 与 CI `禁止 scripts/ 目录`。
