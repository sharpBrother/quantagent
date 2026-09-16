"""日志上下文。``run_id`` 用 ContextVar，避免多命令交叉污染全局 logging。"""

from __future__ import annotations

from contextvars import ContextVar, Token

run_id_var: ContextVar[str] = ContextVar("quantagent_run_id", default="-")


def bind_run_id(run_id: str) -> Token[str]:
    return run_id_var.set(run_id)


def reset_run_id(token: Token[str]) -> None:
    run_id_var.reset(token)
