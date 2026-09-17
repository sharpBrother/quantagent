"""tiny 规模布局 benchmark 必须跑通三类查询并给出 digest。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from quantagent.lake.layout_bench import CANDIDATE_LAYOUTS, run_layout_benchmark

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_tiny_layout_benchmark_runs_three_queries(tmp_path: Path) -> None:
    report = run_layout_benchmark(root=tmp_path, scale="tiny", repeats=1, rebuild=True)
    assert report["scale"] == "tiny"
    assert report["n_rows"] == 12 * 6 * 8
    assert len(report["layouts"]) == len(CANDIDATE_LAYOUTS)
    assert report["digest"]
    for layout in report["layouts"]:
        names = [q["name"] for q in layout["queries"]]
        assert names == [
            "single_factor_window",
            "full_factor_cross_section",
            "training_matrix",
        ]
        for query in layout["queries"]:
            assert query["row_count"] > 0
            assert query["p50_ms"] >= 0
        assert layout["n_files"] >= 1
        assert layout["nbytes"] > 0
