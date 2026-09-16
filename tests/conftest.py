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
