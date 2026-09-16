"""本地路径解析。

所有可变状态都挂在 ``QUANTAGENT_VAR_ROOT`` 下。业务代码禁止自己拼绝对
路径——那是旧仓 88 个文件写死 ``/Users/le`` 的来源。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from quantagent.platform.errors import ConfigError

if TYPE_CHECKING:
    from quantagent.platform.config.settings import Settings

_PYPROJECT_NAME = "quantagent"


@dataclass(frozen=True)
class VarPaths:
    """``var/`` 下约定子目录。调用方需要目录时自己 ``mkdir``，加载配置时不建。"""

    root: Path
    lake: Path
    logs: Path
    runs: Path
    cache: Path
    vintage: Path


def detect_repo_root(start: Path | None = None) -> Path:
    """向上查找含 ``name = "quantagent"`` 的 ``pyproject.toml``。

    用内容匹配而不是目录名，避免工作树或 clone 路径改名后失效。
    """
    seen: set[Path] = set()
    for origin in _search_origins(start):
        for candidate in [origin, *origin.parents]:
            if candidate in seen:
                continue
            seen.add(candidate)
            pyproject = candidate / "pyproject.toml"
            if pyproject.is_file() and _pyproject_is_quantagent(pyproject):
                return candidate
    raise ConfigError(
        '找不到 quantagent 仓库根目录（需要含 project.name = "quantagent" 的 pyproject.toml）'
    )


def resolve_var_paths(settings: Settings, *, repo_root: Path) -> VarPaths:
    raw = settings.var_root
    root = raw if raw.is_absolute() else (repo_root / raw)
    root = root.resolve()
    lake = root / "lake"
    return VarPaths(
        root=root,
        lake=lake,
        logs=root / "logs",
        runs=root / "logs" / "runs",
        cache=root / "cache",
        vintage=lake / "_vintage",
    )


def _search_origins(start: Path | None) -> list[Path]:
    # 显式传入 start 时只在这棵树里找，避免测试或一次性目录误命中真正的仓库。
    if start is not None:
        return [start.resolve()]
    return [Path.cwd().resolve(), Path(__file__).resolve()]


def _pyproject_is_quantagent(path: Path) -> bool:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    project = data.get("project")
    if not isinstance(project, dict):
        return False
    name = project.get("name")
    return isinstance(name, str) and name == _PYPROJECT_NAME
