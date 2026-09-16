"""契约 doc_ref 必须指向真实文档与锚点。文档是解释，契约是权威。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from quantagent.contracts.check import run_check
from quantagent.contracts.loader import load_bundle
from quantagent.platform.storage import detect_repo_root

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.contracts
def test_every_contract_doc_ref_resolves(repo_root: Path) -> None:
    report = run_check(bundle=load_bundle(), repo_root=repo_root)
    binding_issues = [issue for issue in report.issues if "doc_ref" in issue.message]
    assert not binding_issues, "\n".join(issue.render() for issue in binding_issues)


@pytest.mark.contracts
def test_installed_bundle_matches_repo_root(repo_root: Path) -> None:
    """CLI 与测试必须找到同一份仓库根，否则 doc_ref 会指到错误的树。"""
    assert detect_repo_root() == repo_root
