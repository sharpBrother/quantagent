"""缺可见性规则必须失败。这是 PIT fail-closed 的机械门。"""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from quantagent.contracts.check import run_check
from quantagent.contracts.errors import ContractError
from quantagent.contracts.loader import load_bundle

if TYPE_CHECKING:
    from pathlib import Path

_SCHEMA = dedent(
    """\
    dataset: std.demo
    layer: lake
    doc_ref: docs/contracts/demo.md
    temporal_kind: point_event
    event_field: cal_dt
    keys: [cal_dt]
    reads: []
    columns:
      cal_dt:
        dtype: date
        nullable: false
        description: 日历日
    """
)

_VISIBILITY = dedent(
    """\
    dataset: std.demo
    doc_ref: docs/contracts/demo.md
    temporal_kind: point_event
    event_field: cal_dt
    visibility:
      rule: same_day_close
      grade: A
      rationale: 用于测试的合法可见性规则，长度足够
    pit_recoverable: true
    """
)


def _layout(root: Path, *, visibility: bool) -> tuple[dict[str, Path], Path, Path]:
    lake = root / "lake"
    vis = root / "visibility"
    docs = root / "docs" / "contracts"
    lake.mkdir(parents=True)
    vis.mkdir(parents=True)
    docs.mkdir(parents=True)
    (docs / "demo.md").write_text("# demo\n", encoding="utf-8")
    (lake / "std.demo.yaml").write_text(_SCHEMA, encoding="utf-8")
    if visibility:
        (vis / "std.demo.yaml").write_text(_VISIBILITY, encoding="utf-8")
    schema_dirs = {"pg": root / "pg", "ops": root / "ops", "lake": lake}
    return schema_dirs, vis, root


@pytest.mark.unit
def test_missing_visibility_is_fail_closed(tmp_path: Path) -> None:
    schema_dirs, vis, repo = _layout(tmp_path, visibility=False)
    bundle = load_bundle(schema_dirs=schema_dirs, visibility_dir=vis)
    report = run_check(bundle=bundle, repo_root=repo)
    assert report.ok is False
    assert any("缺少可见性规则" in issue.message for issue in report.issues)


@pytest.mark.unit
def test_complete_pair_passes(tmp_path: Path) -> None:
    schema_dirs, vis, repo = _layout(tmp_path, visibility=True)
    bundle = load_bundle(schema_dirs=schema_dirs, visibility_dir=vis)
    report = run_check(bundle=bundle, repo_root=repo)
    assert report.ok, [issue.render() for issue in report.issues]


@pytest.mark.unit
def test_filename_must_match_dataset(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    vis = tmp_path / "visibility"
    lake.mkdir()
    vis.mkdir()
    (lake / "wrong-name.yaml").write_text(_SCHEMA, encoding="utf-8")
    with pytest.raises(ContractError, match="文件名必须与 dataset"):
        load_bundle(
            schema_dirs={"pg": tmp_path / "pg", "ops": tmp_path / "ops", "lake": lake},
            visibility_dir=vis,
        )


@pytest.mark.unit
def test_orphan_visibility_fails(tmp_path: Path) -> None:
    schema_dirs, vis, repo = _layout(tmp_path, visibility=True)
    (schema_dirs["lake"] / "std.demo.yaml").unlink()
    bundle = load_bundle(schema_dirs=schema_dirs, visibility_dir=vis)
    report = run_check(bundle=bundle, repo_root=repo)
    assert report.ok is False
    assert any("没有对应的 schema" in issue.message for issue in report.issues)
