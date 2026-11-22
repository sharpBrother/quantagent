"""因子长表写入前的 PIT 拒绝规则：pit_grade 集合与 knowledge_dt 下界。

拒绝必须发生在任何文件或目录创建之前，且整批拒绝。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest

from quantagent.domain.errors import FeatureLookupError
from quantagent.domain.feature_value import FeatureValue
from quantagent.lake.materialize.feature_value import write_feature_values

if TYPE_CHECKING:
    from pathlib import Path


def _row(
    *,
    asset_id: str = "000001.SZ",
    event_dt: date = date(2024, 1, 15),
    knowledge_dt: date = date(2024, 1, 15),
    pit_grade: str = "A",
) -> FeatureValue:
    return FeatureValue(
        event_dt=event_dt,
        asset_id=asset_id,
        asset_class="stock",
        feature_id="cutamp",
        definition_version="v1",
        param_hash="p0",
        value=1.5,
        knowledge_dt=knowledge_dt,
        pit_grade=pit_grade,
        computed_at=datetime(2024, 6, 1, tzinfo=UTC).replace(tzinfo=None),
        run_id="run-test",
    )


def _files_under(root: Path) -> list[Path]:
    """目标根下的全部条目（文件与目录），用于断言拒绝时没有任何落盘痕迹。"""
    if not root.exists():
        return []
    return list(root.rglob("*"))


@pytest.mark.unit
def test_valid_rows_are_written(tmp_path: Path) -> None:
    dest = tmp_path / "feature" / "value"
    result = write_feature_values([_row(pit_grade="B")], dest)
    assert result["n_files"] >= 1
    assert list(dest.rglob("*.parquet"))


@pytest.mark.unit
@pytest.mark.parametrize("bad_grade", ["Z", "a", "", " A", "A "])
def test_invalid_pit_grade_is_refused_without_files(tmp_path: Path, bad_grade: str) -> None:
    dest = tmp_path / "feature" / "value"
    with pytest.raises(FeatureLookupError, match="pit_grade"):
        write_feature_values([_row(pit_grade=bad_grade)], dest)
    assert _files_under(tmp_path) == []


@pytest.mark.unit
def test_knowledge_dt_before_event_dt_is_refused_without_files(tmp_path: Path) -> None:
    dest = tmp_path / "feature" / "value"
    row = _row(event_dt=date(2024, 1, 15), knowledge_dt=date(2024, 1, 14))
    with pytest.raises(FeatureLookupError, match="knowledge_dt"):
        write_feature_values([row], dest)
    assert _files_under(tmp_path) == []


@pytest.mark.unit
@pytest.mark.parametrize("knowledge_dt", [date(2024, 1, 15), date(2024, 1, 16)])
def test_knowledge_dt_equal_or_later_than_event_dt_is_allowed(
    tmp_path: Path, knowledge_dt: date
) -> None:
    dest = tmp_path / "feature" / "value"
    write_feature_values([_row(knowledge_dt=knowledge_dt)], dest)
    assert list(dest.rglob("*.parquet"))


@pytest.mark.unit
def test_one_bad_row_in_batch_refuses_whole_batch(tmp_path: Path) -> None:
    dest = tmp_path / "feature" / "value"
    good = [_row(asset_id=f"00000{i}.SZ") for i in range(3)]
    bad_last = replace(_row(asset_id="000009.SZ"), pit_grade="E")
    with pytest.raises(FeatureLookupError) as excinfo:
        write_feature_values([*good, bad_last], dest)
    # 错误信息带出坏行的身份与坏字段值，便于定位。
    assert "000009.SZ" in str(excinfo.value)
    assert "'E'" in str(excinfo.value)
    assert _files_under(tmp_path) == []
