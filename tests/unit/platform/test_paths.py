"""路径解析不得依赖写死的机器路径。"""

from __future__ import annotations

from pathlib import Path

import pytest

from quantagent.platform.config import Settings
from quantagent.platform.errors import ConfigError
from quantagent.platform.storage.paths import detect_repo_root, resolve_var_paths


def _write_pyproject(root: Path, name: str = "quantagent") -> None:
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )


@pytest.mark.unit
def test_detect_repo_root_matches_project_name(tmp_path: Path) -> None:
    _write_pyproject(tmp_path)
    nested = tmp_path / "src" / "quantagent"
    nested.mkdir(parents=True)
    assert detect_repo_root(start=nested) == tmp_path


@pytest.mark.unit
def test_detect_repo_root_rejects_other_projects(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, name="other")
    with pytest.raises(ConfigError):
        detect_repo_root(start=tmp_path)


@pytest.mark.unit
def test_relative_var_root_resolves_against_repo(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, var_root=Path("var"))
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    assert paths.root == (tmp_path / "var").resolve()
    assert paths.runs == (tmp_path / "var" / "logs" / "runs").resolve()


@pytest.mark.unit
def test_absolute_var_root_is_kept(tmp_path: Path) -> None:
    abs_root = tmp_path / "data"
    settings = Settings(_env_file=None, var_root=abs_root)
    paths = resolve_var_paths(settings, repo_root=tmp_path / "repo")
    assert paths.root == abs_root.resolve()
