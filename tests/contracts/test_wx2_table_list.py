"""wx2 逐表处置清单契约。

P2 第一个交付物：每张表必须落到五类之一。本测试锁住清单自洽，以及第一批
``src_tables.yaml`` 全部落在类别 1。不连旧库、不迁入。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pytest
import yaml

if TYPE_CHECKING:
    from pathlib import Path

VALID_CATEGORIES = frozenset({1, 2, 3, 4, 5})
REQUIRED_FIELDS = ("name", "row_count", "category", "reason", "dest", "extra")
TABLE_ROW = re.compile(r"^\| `([^`]+)` \|", re.MULTILINE)


def _load_list(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "docs" / "migration" / "wx2-table-list.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), "wx2-table-list.yaml 必须是映射"
    return payload


@pytest.mark.contracts
def test_list_has_unique_complete_rows(repo_root: Path) -> None:
    payload = _load_list(repo_root)
    tables = payload["tables"]
    assert tables, "清单为空"
    names = [row["name"] for row in tables]
    dupes = sorted({name for name in names if names.count(name) > 1})
    assert not dupes, f"清单表名重复：{dupes}"
    missing = [
        f"{row.get('name')}: 缺 {[f for f in REQUIRED_FIELDS if f not in row]}"
        for row in tables
        if any(field not in row for field in REQUIRED_FIELDS)
    ]
    assert not missing, "清单行字段不完整：\n" + "\n".join(missing)
    bad = [
        f"{row['name']}: category={row['category']!r}"
        for row in tables
        if row["category"] not in VALID_CATEGORIES
    ]
    assert not bad, "类别必须是 1–5：\n" + "\n".join(bad)


@pytest.mark.contracts
def test_counts_match_rows(repo_root: Path) -> None:
    payload = _load_list(repo_root)
    tables = payload["tables"]
    counts = payload["counts"]
    by_cat = dict.fromkeys(range(1, 6), 0)
    for row in tables:
        by_cat[int(row["category"])] += 1
    assert counts["total"] == len(tables)
    assert counts["c1"] == by_cat[1]
    assert counts["c2"] == by_cat[2]
    assert counts["c3"] == by_cat[3]
    assert counts["c4"] == by_cat[4]
    assert counts["c5"] == by_cat[5]
    assert sum(by_cat.values()) == len(tables)


@pytest.mark.contracts
def test_src_tables_yaml_are_class_1(repo_root: Path) -> None:
    """第一批源镜像必须全部出现在清单且为类别 1。本测试不授权迁入。"""
    src = yaml.safe_load((repo_root / "db" / "src_tables.yaml").read_text(encoding="utf-8"))
    listed = {row["name"]: row for row in _load_list(repo_root)["tables"]}
    missing: list[str] = []
    wrong: list[str] = []
    for item in src["tables"]:
        name = item["name"]
        if name not in listed:
            missing.append(name)
            continue
        if listed[name]["category"] != 1:
            wrong.append(f"{name}: category={listed[name]['category']}")
        if not listed[name].get("src_batch1"):
            wrong.append(f"{name}: src_batch1 应为 true")
    assert not missing, "src_tables.yaml 有表未进清单：\n" + "\n".join(missing)
    assert not wrong, "第一批源表分类错误：\n" + "\n".join(wrong)


@pytest.mark.contracts
def test_markdown_table_matches_yaml(repo_root: Path) -> None:
    payload = _load_list(repo_root)
    md = (repo_root / "docs" / "migration" / "wx2-table-list.md").read_text(encoding="utf-8")
    names = TABLE_ROW.findall(md)
    yaml_names = [row["name"] for row in payload["tables"]]
    assert names == yaml_names, "markdown 逐表清单必须与 yaml 同序同名"
    assert "不迁入" in md
    assert "不定版 visibility" in md or "不写 PIT YAML" in md
    assert payload["old_commit"] in md


@pytest.mark.contracts
def test_review_baseline_corrections(repo_root: Path) -> None:
    """评审基线：算出来的不进 src_*，schema 跟采集源走，禁止误用 stock_ 前缀。"""
    listed = {row["name"]: row for row in _load_list(repo_root)["tables"]}

    for name in (
        "barra_cne6",
        "barra_cne6_exposure",
        "barra_cne6_factor_return",
        "barra_cne6_specific_return",
        "fina_rpt_forecast",
        "fina_rpt_forecast_roe",
    ):
        assert listed[name]["category"] == 2, name

    etf_min = listed["stock_etf_min_price"]
    assert etf_min["category"] == 1
    assert "etf_min_price" in etf_min["dest"]
    assert "禁止沿用 stock_" in etf_min["dest"]

    assert "src_tushare.eco_cal" in listed["macro_eco_cal"]["dest"]
    assert "src_tushare.shibor" in listed["macro_shibor"]["dest"]
    assert "src_tushare.us_treasury_yield" in listed["macro_us_treasury_yield"]["dest"]

    for name in (
        "fin_income_gen",
        "fin_performance_express",
        "fin_performance_forecast",
        "FIN_APPO_RELE_DATE",
    ):
        assert "src_suntime" in listed[name]["dest"], name
        assert listed[name]["category"] == 1, name
