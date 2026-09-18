"""旧仓文档与制品处置清单契约。

P2 第 5 条：每项必须落到五类之一。本测试锁住清单自洽、markdown 与 yaml 对齐，
以及 bond_timing exhibit freeze 必在类别 1。不迁入。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pytest
import yaml

if TYPE_CHECKING:
    from pathlib import Path

VALID_CATEGORIES = frozenset({1, 2, 3, 4, 5})
REQUIRED_FIELDS = ("path", "category", "reason", "dest", "extra")
ITEM_ROW = re.compile(r"^\| `([^`]+)` \|", re.MULTILINE)
OLD_COMMIT = "7c506d51160e57385fd85217edece815268ffd55"


def _load_list(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "docs" / "migration" / "docs-and-artifacts-list.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), "docs-and-artifacts-list.yaml 必须是映射"
    return payload


@pytest.mark.contracts
def test_list_has_unique_complete_rows(repo_root: Path) -> None:
    payload = _load_list(repo_root)
    items = payload["items"]
    assert items, "清单为空"
    paths = [row["path"] for row in items]
    dupes = sorted({path for path in paths if paths.count(path) > 1})
    assert not dupes, f"清单路径重复：{dupes}"
    missing = [
        f"{row.get('path')}: 缺 {[f for f in REQUIRED_FIELDS if f not in row]}"
        for row in items
        if any(field not in row for field in REQUIRED_FIELDS)
    ]
    assert not missing, "清单行字段不完整：\n" + "\n".join(missing)
    bad = [
        f"{row['path']}: category={row['category']!r}"
        for row in items
        if row["category"] not in VALID_CATEGORIES
    ]
    assert not bad, "类别必须是 1–5：\n" + "\n".join(bad)
    empty = [
        f"{row['path']}: {field} 为空"
        for row in items
        for field in ("path", "reason", "dest", "extra")
        if not str(row.get(field, "")).strip()
    ]
    assert not empty, "依据与去向不得空：\n" + "\n".join(empty)


@pytest.mark.contracts
def test_counts_match_rows(repo_root: Path) -> None:
    payload = _load_list(repo_root)
    items = payload["items"]
    counts = payload["counts"]
    by_cat = dict.fromkeys(range(1, 6), 0)
    for row in items:
        by_cat[int(row["category"])] += 1
    assert counts["total"] == len(items)
    assert counts["c1"] == by_cat[1]
    assert counts["c2"] == by_cat[2]
    assert counts["c3"] == by_cat[3]
    assert counts["c4"] == by_cat[4]
    assert counts["c5"] == by_cat[5]
    assert sum(by_cat.values()) == len(items)
    assert by_cat[1] >= 1
    assert by_cat[2] >= 1
    assert by_cat[4] >= 1
    assert by_cat[5] >= 1


@pytest.mark.contracts
def test_bond_timing_exhibit_freeze_is_class_1(repo_root: Path) -> None:
    """bond_timing exhibit freeze 是已知必迁范例，必须逐项且为类别 1。本测试不授权迁入。"""
    items = _load_list(repo_root)["items"]
    matches = [row for row in items if "bond_timing_exhibit_freeze" in row["path"]]
    assert matches, "清单缺少 outputs/bond_timing_exhibit_freeze"
    assert len(matches) == 1, "bond_timing freeze 应只占一行"
    row = matches[0]
    assert row["category"] == 1
    assert "frozen/" in row["dest"]
    assert "bond_timing" in row["dest"]
    assert "不启动迁入" in row["dest"] or "现不迁" in row["dest"]
    assert row["path"].startswith("outputs/bond_timing_exhibit_freeze")


@pytest.mark.contracts
def test_class_1_destinations_are_frozen(repo_root: Path) -> None:
    listed = _load_list(repo_root)["items"]
    bad = [
        f"{row['path']}: dest={row['dest']!r}"
        for row in listed
        if row["category"] == 1 and "frozen/" not in row["dest"]
    ]
    assert not bad, "类别 1 拟去向必须指向 frozen/：\n" + "\n".join(bad)


@pytest.mark.contracts
def test_markdown_table_matches_yaml(repo_root: Path) -> None:
    payload = _load_list(repo_root)
    md = (repo_root / "docs" / "migration" / "docs-and-artifacts-list.md").read_text(
        encoding="utf-8"
    )
    _, sep, table = md.partition("## 逐项清单")
    assert sep, "markdown 缺少 ## 逐项清单"
    names = ITEM_ROW.findall(table)
    yaml_names = [row["path"] for row in payload["items"]]
    assert names == yaml_names, "markdown 逐项清单必须与 yaml 同序同路径"
    assert "| 路径 | 类别 | 依据 | 拟去向 | 附加约束 |" in md
    assert "不迁入" in md
    assert payload["old_commit"] in md
    assert payload["old_commit"] == OLD_COMMIT
    assert "bond_timing_exhibit_freeze" in md
    _assert_markdown_tables_contiguous(md)


def _assert_markdown_tables_contiguous(md: str) -> None:
    """GFM 在表头分隔行后空一行会把表拆开。"""
    lines = md.splitlines()
    broken: list[str] = []
    for idx, line in enumerate(lines[:-1]):
        if re.fullmatch(r"\|[-: |]+\|", line) and lines[idx + 1] == "":
            broken.append(f"L{idx + 1}: {line}")
    assert not broken, "表头分隔行后不能空行：\n" + "\n".join(broken)


@pytest.mark.contracts
def test_review_baseline_does_not_migrate(repo_root: Path) -> None:
    payload = _load_list(repo_root)
    md = (repo_root / "docs" / "migration" / "docs-and-artifacts-list.md").read_text(
        encoding="utf-8"
    )
    assert "不启动迁入" in payload["migrate_note"]
    assert "P5" in payload["migrate_note"]
    assert "评审基线" in md
    assert "不迁入" in md
    migrated = [
        f"{row['path']}: dest={row['dest']!r}"
        for row in payload["items"]
        if "已迁入" in str(row["dest"])
    ]
    assert not migrated, "清单不得声称已经迁入：\n" + "\n".join(migrated)
