"""Dagster Web 启动入口只使用已有运行目录，且可从任意目录启动。"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.unit
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell 测试在 Linux/macOS 执行")
@pytest.mark.parametrize("explicit_home", [True, False])
def test_shell_launcher_uses_existing_instance_and_loopback(
    tmp_path: Path, explicit_home: bool
) -> None:
    repo = tmp_path / "repo with spaces"
    script = repo / "scripts" / "dagster-web.sh"
    script.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts" / "dagster-web.sh", script)
    bindir = repo / ".venv" / "bin"
    bindir.mkdir(parents=True)
    python = bindir / "python"
    python.write_text('#!/bin/sh\nprintf "%s\\n" "$TEST_DAGSTER_HOME"\n', encoding="utf-8")
    server = bindir / "dagster-webserver"
    server.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$DAGSTER_HOME" "$@" > "$TEST_CAPTURE"\n',
        encoding="utf-8",
    )
    python.chmod(0o755)
    server.chmod(0o755)
    home = tmp_path / "run storage with spaces" / "dagster"
    home.mkdir(parents=True)
    (home / "dagster.yaml").touch()
    (home / "workspace.yaml").touch()
    capture = tmp_path / "arguments.txt"
    env = os.environ.copy()
    env.pop("DAGSTER_HOME", None)
    env["TEST_DAGSTER_HOME"] = str(home)
    env["TEST_CAPTURE"] = str(capture)
    if explicit_home:
        env["DAGSTER_HOME"] = str(home)
    result = subprocess.run(
        ["/bin/sh", str(script)], cwd=tmp_path, env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert capture.read_text(encoding="utf-8").splitlines() == [
        str(home),
        "--host",
        "127.0.0.1",
        "--port",
        "3000",
        "--workspace",
        str(home / "workspace.yaml"),
    ]


@pytest.mark.unit
@pytest.mark.skipif(sys.platform != "win32", reason="Windows cmd 启动入口")
def test_windows_launcher_rejects_missing_workspace(tmp_path: Path) -> None:
    repo = tmp_path / "repo with spaces"
    script = repo / "scripts" / "dagster-web.cmd"
    script.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts" / "dagster-web.cmd", script)
    webserver = repo / ".venv" / "Scripts" / "dagster-webserver.exe"
    webserver.parent.mkdir(parents=True)
    webserver.touch()
    home = tmp_path / "instance with spaces"
    home.mkdir()
    (home / "dagster.yaml").touch()
    env = os.environ.copy()
    env["DAGSTER_HOME"] = str(home)
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Missing Dagster workspace" in result.stdout
    assert str(home) in result.stdout


def _guard_code(command: str) -> str:
    """取 `... -c "<code>"` 里的代码片段；入口前缀不固定（可能是 `uv run python`）。"""
    parts = shlex.split(command)
    return parts[parts.index("-c") + 1]


@pytest.mark.unit
def test_script_guard_allows_only_web_launchers(tmp_path: Path) -> None:
    precommit = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hook = next(
        hook
        for repo in precommit["repos"]
        for hook in repo.get("hooks", [])
        if hook["id"] == "limited-scripts-dir"
    )
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    ci_step = next(
        step
        for step in ci["jobs"]["guardrails"]["steps"]
        if step.get("name") == "scripts/ 只允许 Dagster Web 启动入口"
    )
    # 按 `-c` 定位代码：钩子入口可能带 `uv run` 前缀（macOS 没有 `python`
    # 这个名字），不能按固定下标取参数。
    hook_code = _guard_code(hook["entry"])
    ci_code = _guard_code(ci_step["run"])
    assert hook_code == ci_code
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "dagster-web.cmd").touch()
    (scripts / "dagster-web.sh").touch()
    allowed = subprocess.run(
        [sys.executable, "-c", hook_code], cwd=tmp_path, capture_output=True, check=False
    )
    assert allowed.returncode == 0
    (scripts / "unrelated.py").touch()
    rejected = subprocess.run(
        [sys.executable, "-c", hook_code], cwd=tmp_path, capture_output=True, check=False
    )
    assert rejected.returncode != 0
