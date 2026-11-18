"""pytest 共享配置。

测试分四类，标记在 ``pyproject.toml`` 的 ``markers`` 里声明，组织约定见
``tests/README.md``。这里只放跨类共享的 fixture。

一条硬约束：``unit`` 标记的测试不得依赖任何外部资源。``domain`` 层的规则
测试全部落在这一类，且必须在零数据库、零文件的条件下通过。
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """仓库根目录。测试不得使用任何写死的绝对路径。"""
    return REPO_ROOT


@pytest.fixture(scope="session")
def docs_root(repo_root: Path) -> Path:
    """``docs/`` 根目录，供 frontmatter 与契约绑定校验使用。"""
    return repo_root / "docs"


@pytest.fixture(scope="session")
def frozen_root(repo_root: Path) -> Path:
    """``frozen/`` 根目录，供冻结制品 digest 与行列合同校验使用。"""
    return repo_root / "frozen"


@pytest.fixture(autouse=True)
def _hermetic_quantagent_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试不受本机 shell 环境影响。

    执行机设 ``QUANTAGENT_PROFILE=office``，launchd 只给 daemon 设写闸；这些环境变量会覆盖
    ``Settings(_env_file=None)`` 的默认值，让同一套测试在两台机器上结果不同。仓库 ``.env``
    不受影响，需要真实配置的集成测试照常读取。
    """
    for name in ("QUANTAGENT_PROFILE", "QUANTAGENT_ALLOW_DB_WRITE"):
        monkeypatch.delenv(name, raising=False)
