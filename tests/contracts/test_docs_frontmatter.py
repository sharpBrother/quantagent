"""文档 frontmatter 契约校验。

旧仓 3422 份文档里只有约 7% 带状态字段，导致无法判断一份文档是否还生效。
这组测试把 ``docs/CONVENTIONS.md`` 的公约变成机械检查，避免同样的退化。

``applies_to`` 的路径必须真实存在，这是「改了代码要不要改文档」能有客观
依据的前提。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import yaml

if TYPE_CHECKING:
    from pathlib import Path

REQUIRED_FIELDS = ("title", "status", "created", "updated", "applies_to")
VALID_STATUS = frozenset({"active", "superseded", "archived"})


def _markdown_files(docs_root: Path) -> list[Path]:
    return sorted(docs_root.rglob("*.md"))


def _parse_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        pytest.fail(f"{path} 缺少 frontmatter")
    _, _, rest = text.partition("---\n")
    raw, sep, _ = rest.partition("\n---\n")
    if not sep:
        pytest.fail(f"{path} 的 frontmatter 未闭合")
    parsed = yaml.safe_load(raw)
    if not isinstance(parsed, dict):
        pytest.fail(f"{path} 的 frontmatter 不是映射结构")
    return parsed


def _collect(docs_root: Path) -> dict[Path, dict[str, Any]]:
    return {path: _parse_frontmatter(path) for path in _markdown_files(docs_root)}


@pytest.mark.contracts
def test_docs_exist(docs_root: Path) -> None:
    assert _markdown_files(docs_root), "docs/ 下没有任何 markdown"


@pytest.mark.contracts
def test_required_fields_present(docs_root: Path) -> None:
    missing: list[str] = []
    for path, meta in _collect(docs_root).items():
        absent = [field for field in REQUIRED_FIELDS if field not in meta]
        if absent:
            missing.append(f"{path}: 缺 {absent}")
    assert not missing, "以下文档 frontmatter 不完整：\n" + "\n".join(missing)


@pytest.mark.contracts
def test_status_is_valid(docs_root: Path) -> None:
    invalid = [
        f"{path}: status={meta.get('status')!r}"
        for path, meta in _collect(docs_root).items()
        if meta.get("status") not in VALID_STATUS
    ]
    assert not invalid, "status 取值非法（应为 active/superseded/archived）：\n" + "\n".join(
        invalid
    )


@pytest.mark.contracts
def test_applies_to_paths_exist(docs_root: Path, repo_root: Path) -> None:
    """``applies_to`` 指向的代码路径必须存在，否则文档约束的是已删除的代码。"""
    broken: list[str] = []
    for path, meta in _collect(docs_root).items():
        targets = meta.get("applies_to") or []
        if not isinstance(targets, list):
            broken.append(f"{path}: applies_to 不是列表")
            continue
        broken.extend(
            f"{path}: applies_to 指向不存在的路径 {target}"
            for target in targets
            if not (repo_root / str(target)).exists()
        )
    assert not broken, "\n".join(broken)


@pytest.mark.contracts
def test_superseded_links_resolve(docs_root: Path) -> None:
    """``supersedes`` / ``superseded_by`` 指向的文档必须存在，且状态自洽。"""
    docs = _collect(docs_root)
    problems: list[str] = []
    for path, meta in docs.items():
        for field in ("supersedes", "superseded_by"):
            target = meta.get(field)
            if target in (None, "null", ""):
                continue
            if not (docs_root / str(target)).exists():
                problems.append(f"{path}: {field} 指向不存在的 {target}")
        if (
            meta.get("superseded_by") not in (None, "null", "")
            and meta.get("status") != "superseded"
        ):
            problems.append(f"{path}: 有 superseded_by 但 status 不是 superseded")
    assert not problems, "\n".join(problems)
