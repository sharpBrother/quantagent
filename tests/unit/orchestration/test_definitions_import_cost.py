"""orchestration.definitions 导入期不加载重依赖。

dagster-daemon 只给代码服务器 20 秒心跳。执行机上导入一次重依赖就要数秒，
顶层导入回退后调度会加载失败，见 orchestration/__init__.py。
"""

from __future__ import annotations

import subprocess
import sys

import pytest

_HEAVY = ("pandas", "pyarrow", "duckdb", "pandera", "pymssql", "tushare")


@pytest.mark.unit
def test_definitions_import_does_not_load_heavy_modules() -> None:
    code = (
        "import sys, orchestration.definitions; "
        f"print(','.join(m for m in {_HEAVY!r} if m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""
