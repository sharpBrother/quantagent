"""launchd 模板的静态契约：能被 plist 解析，占位符齐全，写闸只在 launchd 环境里打开。"""

from __future__ import annotations

import plistlib
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

TEMPLATE = "orchestration/launchd/com.quantagent.dagster-daemon.plist.template"
PLACEHOLDERS = ("__REPO__", "__VAR_ROOT__", "__HOME__")


def _load(repo_root: Path) -> dict[str, Any]:
    raw = (repo_root / TEMPLATE).read_bytes()
    parsed = plistlib.loads(raw)
    assert isinstance(parsed, dict)
    return parsed


@pytest.mark.unit
def test_template_parses_as_plist(repo_root: Path) -> None:
    plist = _load(repo_root)
    assert plist["Label"] == "com.quantagent.dagster-daemon"


@pytest.mark.unit
def test_template_keeps_daemon_restart_policy(repo_root: Path) -> None:
    plist = _load(repo_root)
    assert plist["KeepAlive"] == {"SuccessfulExit": False}
    assert plist["RunAtLoad"] is True
    assert plist["ThrottleInterval"] == 60


@pytest.mark.unit
def test_template_runs_launch_script_through_bash(repo_root: Path) -> None:
    args = _load(repo_root)["ProgramArguments"]
    assert args[0] == "/bin/bash"
    assert args[1] == "__VAR_ROOT__/run-dagster-daemon-mac.sh"


@pytest.mark.unit
def test_template_sets_write_gate_only_in_launchd_environment(repo_root: Path) -> None:
    env = _load(repo_root)["EnvironmentVariables"]
    assert env["QUANTAGENT_ALLOW_DB_WRITE"] == "true"
    assert env["QUANTAGENT_PROFILE"] == "local"
    assert env["DAGSTER_HOME"] == "__VAR_ROOT__/dagster"


@pytest.mark.unit
def test_template_uses_placeholders_for_machine_paths(repo_root: Path) -> None:
    text = (repo_root / TEMPLATE).read_text(encoding="utf-8")
    for placeholder in PLACEHOLDERS:
        assert placeholder in text
    assert "/Users/" not in text
    assert "/Volumes/" not in text


@pytest.mark.unit
def test_template_logs_go_under_var_root(repo_root: Path) -> None:
    plist = _load(repo_root)
    assert plist["StandardOutPath"] == "__HOME__/Library/Logs/quantagent/dagster-daemon.out.log"
    assert plist["StandardErrorPath"] == "__HOME__/Library/Logs/quantagent/dagster-daemon.err.log"
    assert plist["WorkingDirectory"] == "__REPO__"
