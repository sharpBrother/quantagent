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
    _, sep, table = md.partition("## 逐表清单")
    assert sep, "markdown 缺少 ## 逐表清单"
    names = TABLE_ROW.findall(table)
    yaml_names = [row["name"] for row in payload["tables"]]
    assert names == yaml_names, "markdown 逐表清单必须与 yaml 同序同名"
    assert "| 表名 | 行数 | 判定类别 | 需PIT |" in md
    assert "## 无需 PIT 的表" in md
    assert "不迁入" in md
    assert "旧仓下游" in md or "data_gateway" in md
    assert payload["old_commit"] in md
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
def test_review_baseline_corrections(repo_root: Path) -> None:
    """评审基线：算出来的不进 src_*，schema 跟采集源走，禁止误用 stock_ 前缀。"""
    listed = {row["name"]: row for row in _load_list(repo_root)["tables"]}
    md = (repo_root / "docs" / "migration" / "wx2-table-list.md").read_text(encoding="utf-8")

    for name in (
        "barra_cne6",
        "barra_cne6_exposure",
        "barra_cne6_factor_return",
        "barra_cne6_specific_return",
        "fina_rpt_forecast",
        "fina_rpt_forecast_roe",
    ):
        assert listed[name]["category"] == 2, name

    assert "feature.value" in listed["barra_cne6"]["dest"]
    assert "不建 barra_*" in listed["barra_cne6"]["dest"]
    assert "feature.value" in listed["barra_cne6_exposure"]["dest"]
    assert "不建表" in listed["barra_cne6_factor_return"]["dest"]
    assert "进不了 feature.value" in listed["barra_cne6_factor_return"]["dest"]
    assert "不进 feature.value" in listed["barra_cne6_specific_return"]["dest"]

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

    no_pit = {
        "CT_SystemConst",
        "SecuMain",
        "SecuMainAll",
        "C_ED_IndicatorMain",
        "ASHAREDESCRIPTION",
        "AINDEXINDUSTRIESCITICS",
        "tushare_ths_industry_mapping_citics",
        "mapping_industry_etf",
        "strategy_etf_list",
        "strategy_etf_list_2",
        "universe_style_rotation",
    }
    for name in no_pit:
        assert listed[name].get("pit_required") is False, name
        assert "无需 PIT" in listed[name]["extra"], name
        assert f"`{name}`" in md, name
    assert listed["AINDEXMEMBERS"].get("pit_required") is not False
    assert listed["trade_cal"].get("pit_required") is not False
    assert listed["ASHARESECNINDUSTRIESCLASS"].get("pit_required") is not False

    assert listed["strategy_etf_black_list"].get("pit_required") is not False
    assert "universe_id=universe_etf。" in listed["strategy_etf_list"]["dest"]
    assert "universe_id=universe_etf_2" in listed["strategy_etf_list_2"]["dest"]
    assert "universe_etf_rebate" in listed["strategy_etf_list_rebate"]["dest"]
    assert "universe_etf_blacklist" in listed["strategy_etf_black_list"]["dest"]
    assert "universe_etf_pool" in listed["strategy_etf_pool"]["dest"]
    assert "类似 ASHAREDESCRIPTION" in listed["strategy_etf_list"]["extra"]
    assert "universe_etf_*" in md
    assert "`strategy_etf_list`" in md
    assert listed["strategy_etf_list"]["dest"] in md
    for name in (
        "ASHAREINCOME",
        "ASHAREBALANCESHEET",
        "ASHARECASHFLOW",
        "ASHAREFINANCIALINDICATOR",
    ):
        assert "ANN_DT<=as_of" in listed[name]["extra"], name
    assert "ANN_DT <= as_of" in md
