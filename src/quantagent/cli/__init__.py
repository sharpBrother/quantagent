"""cli：统一命令行入口，也是一个 composition root。

负责：``quantagent <group> <command>`` 的命令分组与参数解析，以及把
``adapters`` 的具体实现注入到业务层依赖的 ``domain.ports`` Protocol。

**本仓库没有 scripts/ 目录。** 所有可执行入口只有两处来源：本模块的 CLI
子命令，和 ``orchestration/`` 的 Dagster asset/job。探索性代码只能进
``notebooks/``。这条规则用来根治旧仓「316 个脚本、约 81% 无归属、找不到
想要的那个」的问题。

允许依赖：全部层（composition root 的特权）。反之业务层不得依赖 ``cli``。

见 ``docs/architecture/cli-and-orchestration.md``。
"""

__all__: list[str] = []
